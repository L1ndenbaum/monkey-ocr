package storage

import (
	"context"

	domain "monkeyocr-storage-service/internal/domain/storage"
)

type Service struct {
	repository Repository
}

func NewService(repository Repository) *Service {
	return &Service{repository: repository}
}

func (service *Service) EnsureBucket(ctx context.Context, bucket string) error {
	if bucket == "" {
		return domain.ErrBucketRequired
	}
	return service.repository.EnsureBucket(ctx, bucket)
}

func (service *Service) CreateMultipartUpload(
	ctx context.Context,
	request domain.CreateMultipartRequest,
) (domain.MultipartUpload, error) {
	if err := request.Validate(); err != nil {
		return domain.MultipartUpload{}, err
	}
	return service.repository.CreateMultipartUpload(ctx, request)
}

func (service *Service) CompleteMultipartUpload(
	ctx context.Context,
	request domain.CompleteMultipartRequest,
) (domain.CompleteMultipartResult, error) {
	if err := request.Validate(); err != nil {
		return domain.CompleteMultipartResult{}, err
	}
	return service.repository.CompleteMultipartUpload(ctx, request)
}

func (service *Service) AbortMultipartUpload(ctx context.Context, request domain.AbortMultipartRequest) error {
	if err := request.Validate(); err != nil {
		return err
	}
	return service.repository.AbortMultipartUpload(ctx, request)
}

func (service *Service) PresignGetObject(ctx context.Context, ref domain.ObjectRef, expiresIn int) (string, error) {
	if err := ref.Validate(); err != nil {
		return "", err
	}
	return service.repository.PresignGetObject(ctx, ref, expiresIn)
}

func (service *Service) PresignPutObject(ctx context.Context, ref domain.ObjectRef, contentType string, expiresIn int) (string, error) {
	if err := ref.Validate(); err != nil {
		return "", err
	}
	return service.repository.PresignPutObject(ctx, ref, contentType, expiresIn)
}

func (service *Service) StatObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStat, error) {
	if err := ref.Validate(); err != nil {
		return domain.ObjectStat{}, err
	}
	return service.repository.StatObject(ctx, ref)
}

func (service *Service) GetObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStream, error) {
	if err := ref.Validate(); err != nil {
		return domain.ObjectStream{}, err
	}
	return service.repository.GetObject(ctx, ref)
}

func (service *Service) DeleteObject(ctx context.Context, ref domain.ObjectRef) error {
	if err := ref.Validate(); err != nil {
		return err
	}
	return service.repository.DeleteObject(ctx, ref)
}

func (service *Service) PutObject(ctx context.Context, input PutObjectInput) (domain.PutObjectResult, error) {
	if err := (domain.ObjectRef{Bucket: input.Bucket, ObjectKey: input.ObjectKey}).Validate(); err != nil {
		return domain.PutObjectResult{}, err
	}
	return service.repository.PutObject(ctx, input)
}
