package httpapi

import domain "monkeyocr-storage-service/internal/domain/storage"

type ensureBucketRequest struct {
	Bucket string `json:"bucket"`
}

type createMultipartRequest struct {
	Bucket      string            `json:"bucket"`
	ObjectKey   string            `json:"object_key"`
	ContentType string            `json:"content_type"`
	Metadata    map[string]string `json:"metadata"`
	PartCount   int               `json:"part_count"`
	ExpiresIn   int               `json:"expires_in"`
}

type partURL struct {
	PartNumber int    `json:"part_number"`
	URL        string `json:"url"`
}

type completePart struct {
	PartNumber int    `json:"part_number"`
	ETag       string `json:"etag"`
}

type completeMultipartRequest struct {
	Bucket    string         `json:"bucket"`
	ObjectKey string         `json:"object_key"`
	UploadID  string         `json:"upload_id"`
	Parts     []completePart `json:"parts"`
}

type objectRequest struct {
	Bucket    string `json:"bucket"`
	ObjectKey string `json:"object_key"`
	ExpiresIn int    `json:"expires_in"`
}

type presignPutRequest struct {
	Bucket      string `json:"bucket"`
	ObjectKey   string `json:"object_key"`
	ContentType string `json:"content_type"`
	ExpiresIn   int    `json:"expires_in"`
}

func toCreateMultipartDomain(request createMultipartRequest) domain.CreateMultipartRequest {
	return domain.CreateMultipartRequest{
		Bucket:      request.Bucket,
		ObjectKey:   request.ObjectKey,
		ContentType: request.ContentType,
		Metadata:    request.Metadata,
		PartCount:   request.PartCount,
		ExpiresIn:   request.ExpiresIn,
	}
}

func toCompleteMultipartDomain(request completeMultipartRequest) domain.CompleteMultipartRequest {
	parts := make([]domain.CompletedPart, 0, len(request.Parts))
	for _, part := range request.Parts {
		parts = append(parts, domain.CompletedPart{PartNumber: part.PartNumber, ETag: part.ETag})
	}

	return domain.CompleteMultipartRequest{
		Bucket:    request.Bucket,
		ObjectKey: request.ObjectKey,
		UploadID:  request.UploadID,
		Parts:     parts,
	}
}

func toAbortMultipartDomain(request completeMultipartRequest) domain.AbortMultipartRequest {
	return domain.AbortMultipartRequest{
		Bucket:    request.Bucket,
		ObjectKey: request.ObjectKey,
		UploadID:  request.UploadID,
	}
}

func toPartURLs(parts []domain.MultipartPartURL) []partURL {
	responseParts := make([]partURL, 0, len(parts))
	for _, part := range parts {
		responseParts = append(responseParts, partURL{PartNumber: part.PartNumber, URL: part.URL})
	}
	return responseParts
}
