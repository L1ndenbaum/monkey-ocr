package storage

type CreateMultipartRequest struct {
	Bucket      string
	ObjectKey   string
	ContentType string
	Metadata    map[string]string
	PartCount   int
	ExpiresIn   int
}

type MultipartPartURL struct {
	PartNumber int
	URL        string
}

type MultipartUpload struct {
	Bucket    string
	ObjectKey string
	UploadID  string
	Parts     []MultipartPartURL
}

type CompletedPart struct {
	PartNumber int
	ETag       string
}

type CompleteMultipartRequest struct {
	Bucket    string
	ObjectKey string
	UploadID  string
	Parts     []CompletedPart
}

type AbortMultipartRequest struct {
	Bucket    string
	ObjectKey string
	UploadID  string
}

type CompleteMultipartResult struct {
	Bucket    string
	ObjectKey string
	ETag      string
}

func (request CreateMultipartRequest) Validate() error {
	if err := (ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey}).Validate(); err != nil {
		return err
	}
	if request.PartCount <= 0 {
		return ErrInvalidPartCount
	}
	return nil
}

func (request CompleteMultipartRequest) Validate() error {
	if err := (ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey}).Validate(); err != nil {
		return err
	}
	if request.UploadID == "" {
		return ErrUploadIDRequired
	}
	if len(request.Parts) == 0 {
		return ErrMultipartPartsRequired
	}
	return nil
}

func (request AbortMultipartRequest) Validate() error {
	if err := (ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey}).Validate(); err != nil {
		return err
	}
	if request.UploadID == "" {
		return ErrUploadIDRequired
	}
	return nil
}
