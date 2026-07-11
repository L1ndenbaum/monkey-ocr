package storage

import "errors"

var (
	ErrBucketRequired         = errors.New("bucket is required")
	ErrObjectKeyRequired      = errors.New("object_key is required")
	ErrInvalidPartCount       = errors.New("positive part_count is required")
	ErrMultipartPartsRequired = errors.New("parts are required")
	ErrUploadIDRequired       = errors.New("upload_id is required")
	ErrObjectNotFound         = errors.New("object not found")
)
