package storage

import (
	"context"
	"io"

	domain "monkeyocr-storage-service/internal/domain/storage"
)

type PutObjectInput struct {
	Bucket        string
	ObjectKey     string
	Body          io.ReadSeeker
	ContentLength int64
	ContentType   string
}

type Repository interface {
	EnsureBucket(ctx context.Context, bucket string) error
	CreateMultipartUpload(ctx context.Context, request domain.CreateMultipartRequest) (domain.MultipartUpload, error)
	CompleteMultipartUpload(ctx context.Context, request domain.CompleteMultipartRequest) (domain.CompleteMultipartResult, error)
	AbortMultipartUpload(ctx context.Context, request domain.AbortMultipartRequest) error
	PresignGetObject(ctx context.Context, ref domain.ObjectRef, expiresIn int) (string, error)
	PresignPutObject(ctx context.Context, ref domain.ObjectRef, contentType string, expiresIn int) (string, error)
	StatObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStat, error)
	GetObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStream, error)
	DeleteObject(ctx context.Context, ref domain.ObjectRef) error
	PutObject(ctx context.Context, input PutObjectInput) (domain.PutObjectResult, error)
}
