package s3storage

import (
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"monkeyocr-storage-service/internal/config"
)

type Clients struct {
	Internal *s3.Client
	Presign  *s3.PresignClient
}

func NewClients(cfg config.Config) Clients {
	internalClient := newS3Client(cfg.InternalEndpoint, cfg.MinIORegion, cfg.AccessKey, cfg.SecretKey)
	publicClient := newS3Client(cfg.PublicEndpoint, cfg.MinIORegion, cfg.AccessKey, cfg.SecretKey)

	return Clients{
		Internal: internalClient,
		Presign:  s3.NewPresignClient(publicClient),
	}
}

func endpointResolver(endpoint string) aws.EndpointResolverWithOptions {
	return aws.EndpointResolverWithOptionsFunc(
		func(service, region string, options ...interface{}) (aws.Endpoint, error) {
			return aws.Endpoint{URL: endpoint, HostnameImmutable: true}, nil
		},
	)
}

func newS3Client(endpoint, region, accessKey, secretKey string) *s3.Client {
	cfg := aws.Config{
		Region: region,
		Credentials: aws.NewCredentialsCache(
			credentials.NewStaticCredentialsProvider(accessKey, secretKey, ""),
		),
		EndpointResolverWithOptions: endpointResolver(endpoint),
	}
	return s3.NewFromConfig(cfg, func(options *s3.Options) {
		options.UsePathStyle = true
	})
}
