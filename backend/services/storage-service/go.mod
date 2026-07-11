module monkeyocr-storage-service

go 1.22

require (
	github.com/aws/aws-sdk-go-v2 v1.29.0
	github.com/aws/aws-sdk-go-v2/credentials v1.17.20
	github.com/aws/aws-sdk-go-v2/service/s3 v1.54.2
	github.com/aws/smithy-go v1.20.2
	monkeyocr-services-lib-go v0.0.0
)

replace monkeyocr-services-lib-go => ../lib-go

require (
	github.com/aws/aws-sdk-go-v2/aws/protocol/eventstream v1.6.2 // indirect
	github.com/aws/aws-sdk-go-v2/internal/configsources v1.3.11 // indirect
	github.com/aws/aws-sdk-go-v2/internal/endpoints/v2 v2.6.11 // indirect
	github.com/aws/aws-sdk-go-v2/internal/v4a v1.3.7 // indirect
	github.com/aws/aws-sdk-go-v2/service/internal/accept-encoding v1.11.2 // indirect
	github.com/aws/aws-sdk-go-v2/service/internal/checksum v1.3.9 // indirect
	github.com/aws/aws-sdk-go-v2/service/internal/presigned-url v1.11.13 // indirect
	github.com/aws/aws-sdk-go-v2/service/internal/s3shared v1.17.7 // indirect
	github.com/go-chi/chi/v5 v5.2.3 // indirect
)
