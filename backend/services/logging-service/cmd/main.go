package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	applogging "monkeyocr-logging-service/internal/application/logging"
	"monkeyocr-logging-service/internal/config"
	"monkeyocr-logging-service/internal/infrastructure/filesink"
	kafkapub "monkeyocr-logging-service/internal/infrastructure/kafka"
	"monkeyocr-logging-service/internal/interfaces/console"
	httpapi "monkeyocr-logging-service/internal/interfaces/http"
	httpserver "monkeyocr-services-lib-go/http/server"
)

const kafkaStartupCheckTimeout = 10 * time.Second

// main wires configuration, sinks, Kafka publishing, and the HTTP server lifecycle.
func main() {
	cfg := config.Load()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	publisher := kafkapub.NewPublisher(cfg.KafkaBrokers, cfg.KafkaTopic)
	checkCtx, cancelCheck := context.WithTimeout(ctx, kafkaStartupCheckTimeout)
	if err := publisher.Check(checkCtx); err != nil {
		cancelCheck()
		log.Panicf(
			"kafka startup check failed for brokers=%v topic=%q: %v",
			cfg.KafkaBrokers,
			cfg.KafkaTopic,
			err,
		)
	}
	cancelCheck()
	defer func() {
		if err := publisher.Close(); err != nil {
			log.Printf("kafka publisher close failed: %v", err)
		}
	}()

	fallbackStore := filesink.NewKafkaFallbackStore(cfg.SpoolFile, cfg.ErrorAuditFile)
	fallbackStore.StartReplay(ctx, publisher, cfg.ReplayInterval)

	service := applogging.NewServiceWithFallback(
		applogging.Config{
			FlushInterval: cfg.FlushInterval,
			QueueSize:     cfg.QueueSize,
			MaxBatchSize:  cfg.MaxBatchSize,
		},
		[]applogging.BatchSink{
			&console.Sink{Writer: os.Stdout, Color: cfg.ConsoleColor},
		},
		fallbackStore,
		publisher,
	)
	serviceCtx, stopService := context.WithCancel(context.Background())
	defer stopService()
	service.Start(serviceCtx)

	handler := httpapi.NewHandler(service, cfg.ServiceToken)
	server := httpserver.New(cfg.HTTPServerConfig(), httpapi.NewRouter(handler))

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			log.Printf("logging-service shutdown failed: %v", err)
		}
		if err := service.Shutdown(shutdownCtx); err != nil {
			log.Printf("logging-service drain failed: %v", err)
		}
		stopService()
	}()

	log.Printf("logging-service listening on %s", cfg.Addr)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
