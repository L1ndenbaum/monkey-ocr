package s3storage

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	smithy "github.com/aws/smithy-go"

	appstorage "monkeyocr-storage-service/internal/application/storage"
	domain "monkeyocr-storage-service/internal/domain/storage"
)

type Repository struct {
	client  *s3.Client
	presign *s3.PresignClient
}

func NewRepository(client *s3.Client, presign *s3.PresignClient) *Repository {
	return &Repository{client: client, presign: presign}
}

func (repository *Repository) EnsureBucket(ctx context.Context, bucket string) error {
	_, err := repository.client.HeadBucket(ctx, &s3.HeadBucketInput{Bucket: aws.String(bucket)})
	if err == nil {
		return nil
	}

	_, err = repository.client.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String(bucket)})
	return err
}

func (repository *Repository) CreateMultipartUpload(
	ctx context.Context,
	request domain.CreateMultipartRequest,
) (domain.MultipartUpload, error) {
	expires := expiresDuration(request.ExpiresIn)
	out, err := repository.client.CreateMultipartUpload(ctx, &s3.CreateMultipartUploadInput{
		Bucket:      aws.String(request.Bucket),
		Key:         aws.String(request.ObjectKey),
		ContentType: aws.String(request.ContentType),
		Metadata:    request.Metadata,
	})
	if err != nil {
		return domain.MultipartUpload{}, err
	}

	parts := make([]domain.MultipartPartURL, 0, request.PartCount)
	for partNumber := 1; partNumber <= request.PartCount; partNumber++ {
		presigned, err := repository.presign.PresignUploadPart(
			context.Background(),
			&s3.UploadPartInput{
				Bucket:     aws.String(request.Bucket),
				Key:        aws.String(request.ObjectKey),
				UploadId:   out.UploadId,
				PartNumber: aws.Int32(int32(partNumber)),
			},
			func(options *s3.PresignOptions) { options.Expires = expires },
		)
		if err != nil {
			_, _ = repository.client.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{
				Bucket:   aws.String(request.Bucket),
				Key:      aws.String(request.ObjectKey),
				UploadId: out.UploadId,
			})
			return domain.MultipartUpload{}, err
		}
		parts = append(parts, domain.MultipartPartURL{PartNumber: partNumber, URL: presigned.URL})
	}

	return domain.MultipartUpload{
		Bucket:    request.Bucket,
		ObjectKey: request.ObjectKey,
		UploadID:  aws.ToString(out.UploadId),
		Parts:     parts,
	}, nil
}

func (repository *Repository) CompleteMultipartUpload(
	ctx context.Context,
	request domain.CompleteMultipartRequest,
) (domain.CompleteMultipartResult, error) {
	sort.Slice(request.Parts, func(i, j int) bool {
		return request.Parts[i].PartNumber < request.Parts[j].PartNumber
	})

	parts := make([]types.CompletedPart, 0, len(request.Parts))
	for _, part := range request.Parts {
		parts = append(parts, types.CompletedPart{
			ETag:       aws.String(normalizeETag(part.ETag)),
			PartNumber: aws.Int32(int32(part.PartNumber)),
		})
	}

	out, err := repository.client.CompleteMultipartUpload(ctx, &s3.CompleteMultipartUploadInput{
		Bucket:   aws.String(request.Bucket),
		Key:      aws.String(request.ObjectKey),
		UploadId: aws.String(request.UploadID),
		MultipartUpload: &types.CompletedMultipartUpload{
			Parts: parts,
		},
	})
	if err != nil {
		return domain.CompleteMultipartResult{}, err
	}

	return domain.CompleteMultipartResult{
		Bucket:    request.Bucket,
		ObjectKey: request.ObjectKey,
		ETag:      trimETag(aws.ToString(out.ETag)),
	}, nil
}

func (repository *Repository) AbortMultipartUpload(ctx context.Context, request domain.AbortMultipartRequest) error {
	_, err := repository.client.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{
		Bucket:   aws.String(request.Bucket),
		Key:      aws.String(request.ObjectKey),
		UploadId: aws.String(request.UploadID),
	})
	if err != nil && isNoSuchUpload(err) {
		return nil
	}
	return err
}

func (repository *Repository) PresignGetObject(
	ctx context.Context,
	ref domain.ObjectRef,
	expiresIn int,
) (string, error) {
	presigned, err := repository.presign.PresignGetObject(
		context.Background(),
		&s3.GetObjectInput{Bucket: aws.String(ref.Bucket), Key: aws.String(ref.ObjectKey)},
		func(options *s3.PresignOptions) { options.Expires = expiresDuration(expiresIn) },
	)
	if err != nil {
		return "", err
	}
	return presigned.URL, nil
}

func (repository *Repository) PresignPutObject(
	ctx context.Context,
	ref domain.ObjectRef,
	contentType string,
	expiresIn int,
) (string, error) {
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	presigned, err := repository.presign.PresignPutObject(
		context.Background(),
		&s3.PutObjectInput{
			Bucket:      aws.String(ref.Bucket),
			Key:         aws.String(ref.ObjectKey),
			ContentType: aws.String(contentType),
		},
		func(options *s3.PresignOptions) { options.Expires = expiresDuration(expiresIn) },
	)
	if err != nil {
		return "", err
	}
	return presigned.URL, nil
}

func (repository *Repository) StatObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStat, error) {
	out, err := repository.client.HeadObject(ctx, &s3.HeadObjectInput{
		Bucket: aws.String(ref.Bucket),
		Key:    aws.String(ref.ObjectKey),
	})
	if err != nil {
		if isNotFound(err) {
			return domain.ObjectStat{}, domain.ErrObjectNotFound
		}
		return domain.ObjectStat{}, err
	}

	return domain.ObjectStat{
		Bucket:      ref.Bucket,
		ObjectKey:   ref.ObjectKey,
		Size:        aws.ToInt64(out.ContentLength),
		ETag:        trimETag(aws.ToString(out.ETag)),
		ContentType: aws.ToString(out.ContentType),
		Metadata:    out.Metadata,
	}, nil
}

func (repository *Repository) GetObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStream, error) {
	out, err := repository.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(ref.Bucket),
		Key:    aws.String(ref.ObjectKey),
	})
	if err != nil {
		if isNotFound(err) {
			return domain.ObjectStream{}, domain.ErrObjectNotFound
		}
		return domain.ObjectStream{}, err
	}

	return domain.ObjectStream{
		Bucket:      ref.Bucket,
		ObjectKey:   ref.ObjectKey,
		Body:        out.Body,
		Size:        aws.ToInt64(out.ContentLength),
		ETag:        trimETag(aws.ToString(out.ETag)),
		ContentType: aws.ToString(out.ContentType),
	}, nil
}

func (repository *Repository) DeleteObject(ctx context.Context, ref domain.ObjectRef) error {
	_, err := repository.client.DeleteObject(ctx, &s3.DeleteObjectInput{
		Bucket: aws.String(ref.Bucket),
		Key:    aws.String(ref.ObjectKey),
	})
	return err
}

func (repository *Repository) PutObject(
	ctx context.Context,
	input appstorage.PutObjectInput,
) (domain.PutObjectResult, error) {
	contentType := input.ContentType
	if contentType == "" {
		contentType = "application/octet-stream"
	}

	out, err := repository.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(input.Bucket),
		Key:           aws.String(input.ObjectKey),
		Body:          input.Body,
		ContentType:   aws.String(contentType),
		ContentLength: aws.Int64(input.ContentLength),
	})
	if err != nil {
		return domain.PutObjectResult{}, err
	}

	return domain.PutObjectResult{
		Bucket:    input.Bucket,
		ObjectKey: input.ObjectKey,
		ETag:      trimETag(aws.ToString(out.ETag)),
	}, nil
}

func normalizeETag(etag string) string {
	trimmed := strings.TrimSpace(etag)
	if strings.HasPrefix(trimmed, "\"") && strings.HasSuffix(trimmed, "\"") {
		return trimmed
	}
	return fmt.Sprintf("\"%s\"", strings.Trim(trimmed, "\""))
}

func trimETag(etag string) string {
	return strings.Trim(etag, "\"")
}

func expiresDuration(seconds int) time.Duration {
	if seconds <= 0 {
		seconds = 900
	}
	return time.Duration(seconds) * time.Second
}

func isNotFound(err error) bool {
	var apiErr smithy.APIError
	if errors.As(err, &apiErr) {
		code := apiErr.ErrorCode()
		return code == "NotFound" || code == "NoSuchKey" || code == "NoSuchBucket"
	}
	return false
}

func isNoSuchUpload(err error) bool {
	var apiErr smithy.APIError
	return errors.As(err, &apiErr) && apiErr.ErrorCode() == "NoSuchUpload"
}
