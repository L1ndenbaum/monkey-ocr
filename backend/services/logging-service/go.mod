module monkeyocr-logging-service

go 1.22

require (
	github.com/segmentio/kafka-go v0.4.47
	monkeyocr-services-lib-go v0.0.0
)

replace monkeyocr-services-lib-go => ../lib-go

require (
	github.com/go-chi/chi/v5 v5.2.3 // indirect
	github.com/klauspost/compress v1.15.9 // indirect
	github.com/pierrec/lz4/v4 v4.1.15 // indirect
	github.com/stretchr/testify v1.9.0 // indirect
)
