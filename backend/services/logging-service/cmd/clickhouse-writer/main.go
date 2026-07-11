package main

import (
	"context"
	"errors"
	"log"
	"os/signal"
	"syscall"
	"time"

	appwriter "monkeyocr-logging-service/internal/application/clickhousewriter"
	"monkeyocr-logging-service/internal/config"
	"monkeyocr-logging-service/internal/infrastructure/clickhouse"

	segmentio "github.com/segmentio/kafka-go"
)

// main consumes logging Kafka events and writes them to ClickHouse in batches.
func main() {
	cfg := config.LoadClickHouseWriter()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	reader := segmentio.NewReader(segmentio.ReaderConfig{
		Brokers:        cfg.KafkaBrokers,
		Topic:          cfg.KafkaTopic,
		GroupID:        cfg.KafkaGroupID,
		MinBytes:       1,
		MaxBytes:       10e6,
		CommitInterval: 0,
	})
	defer reader.Close()

	inserter := clickhouse.NewHTTPWriter(clickhouse.HTTPWriterConfig{
		BaseURL:  cfg.ClickHouseHTTPURL,
		Database: cfg.ClickHouseDatabase,
		Table:    cfg.ClickHouseTable,
		Username: cfg.ClickHouseUser,
		Password: cfg.ClickHousePassword,
		Timeout:  cfg.HTTPTimeout,
	})
	committer := &kafkaCommitter{reader: reader}

	log.Printf("clickhouse-writer consuming topic=%s group=%s", cfg.KafkaTopic, cfg.KafkaGroupID)
	if err := run(ctx, reader, inserter, committer, cfg.BatchSize, cfg.FlushInterval); err != nil {
		log.Fatal(err)
	}
}

func run(
	ctx context.Context,
	reader *segmentio.Reader,
	inserter appwriter.Inserter,
	committer appwriter.Committer,
	batchSize int,
	flushInterval time.Duration,
) error {
	if batchSize <= 0 {
		batchSize = 500
	}
	if flushInterval <= 0 {
		flushInterval = time.Second
	}

	batch := make([]appwriter.Message, 0, batchSize)
	flush := func() error {
		if len(batch) == 0 {
			return nil
		}
		processing := append([]appwriter.Message(nil), batch...)
		if err := appwriter.ProcessBatch(ctx, processing, inserter, committer); err != nil {
			return err
		}
		batch = batch[:0]
		return nil
	}

	for {
		if len(batch) >= batchSize {
			if err := flush(); err != nil {
				log.Printf("clickhouse batch flush failed: %v", err)
				time.Sleep(time.Second)
			}
			continue
		}

		fetchCtx := ctx
		cancel := func() {}
		if len(batch) > 0 {
			var timeoutCancel context.CancelFunc
			fetchCtx, timeoutCancel = context.WithTimeout(ctx, flushInterval)
			cancel = timeoutCancel
		}

		message, err := reader.FetchMessage(fetchCtx)
		cancel()
		if err != nil {
			if errors.Is(err, context.DeadlineExceeded) && len(batch) > 0 {
				if flushErr := flush(); flushErr != nil {
					log.Printf("clickhouse batch flush failed: %v", flushErr)
				}
				continue
			}
			if ctx.Err() != nil {
				return flush()
			}
			log.Printf("kafka fetch failed: %v", err)
			time.Sleep(time.Second)
			continue
		}

		batch = append(batch, appwriter.Message{Value: message.Value, Handle: message})
		if len(batch) >= batchSize {
			if err := flush(); err != nil {
				log.Printf("clickhouse batch flush failed: %v", err)
			}
		}
	}
}

type kafkaCommitter struct {
	reader *segmentio.Reader
}

func (committer *kafkaCommitter) Commit(ctx context.Context, messages []appwriter.Message) error {
	kafkaMessages := make([]segmentio.Message, 0, len(messages))
	for _, message := range messages {
		kafkaMessage, ok := message.Handle.(segmentio.Message)
		if !ok {
			continue
		}
		kafkaMessages = append(kafkaMessages, kafkaMessage)
	}
	if len(kafkaMessages) == 0 {
		return nil
	}
	return committer.reader.CommitMessages(ctx, kafkaMessages...)
}
