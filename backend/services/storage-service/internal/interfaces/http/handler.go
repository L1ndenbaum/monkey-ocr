package httpapi

import (
	"errors"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"

	sharedhttp "monkeyocr-services-lib-go/http/api"
	appstorage "monkeyocr-storage-service/internal/application/storage"
	domain "monkeyocr-storage-service/internal/domain/storage"
)

type Handler struct {
	storageService     *appstorage.Service
	serviceToken       string
	maxUploadBodyBytes int64
}

const defaultMaxUploadBodyBytes int64 = 512 << 20

type HandlerOption func(*Handler)

// WithMaxUploadBodyBytes sets the maximum accepted PUT object body size.
func WithMaxUploadBodyBytes(limit int64) HandlerOption {
	return func(handler *Handler) {
		if limit > 0 {
			handler.maxUploadBodyBytes = limit
		}
	}
}

// NewHandler binds the storage application service, service token, and HTTP limits.
func NewHandler(storageService *appstorage.Service, serviceToken string, options ...HandlerOption) *Handler {
	handler := &Handler{
		storageService:     storageService,
		serviceToken:       serviceToken,
		maxUploadBodyBytes: defaultMaxUploadBodyBytes,
	}
	for _, option := range options {
		option(handler)
	}
	return handler
}

func (handler *Handler) HandleHealth(w http.ResponseWriter, r *http.Request) {
	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (handler *Handler) HandleEnsureBucket(w http.ResponseWriter, r *http.Request) {
	var request ensureBucketRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	err := handler.storageService.EnsureBucket(r.Context(), request.Bucket)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"bucket": request.Bucket})
}

func (handler *Handler) HandleCreateMultipart(w http.ResponseWriter, r *http.Request) {
	var request createMultipartRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	upload, err := handler.storageService.CreateMultipartUpload(
		r.Context(),
		toCreateMultipartDomain(request),
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]any{
		"bucket":     upload.Bucket,
		"object_key": upload.ObjectKey,
		"upload_id":  upload.UploadID,
		"parts":      toPartURLs(upload.Parts),
	})
}

func (handler *Handler) HandleCompleteMultipart(w http.ResponseWriter, r *http.Request) {
	var request completeMultipartRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	result, err := handler.storageService.CompleteMultipartUpload(
		r.Context(),
		toCompleteMultipartDomain(request),
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]any{
		"bucket":     result.Bucket,
		"object_key": result.ObjectKey,
		"etag":       result.ETag,
	})
}

func (handler *Handler) HandleAbortMultipart(w http.ResponseWriter, r *http.Request) {
	var request completeMultipartRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	err := handler.storageService.AbortMultipartUpload(r.Context(), toAbortMultipartDomain(request))
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"status": "aborted"})
}

func (handler *Handler) HandlePresignGet(w http.ResponseWriter, r *http.Request) {
	var request objectRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	url, err := handler.storageService.PresignGetObject(
		r.Context(),
		domain.ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey},
		request.ExpiresIn,
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"url": url})
}

func (handler *Handler) HandlePresignPut(w http.ResponseWriter, r *http.Request) {
	var request presignPutRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	url, err := handler.storageService.PresignPutObject(
		r.Context(),
		domain.ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey},
		request.ContentType,
		request.ExpiresIn,
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"url": url})
}

func (handler *Handler) HandleStatObject(w http.ResponseWriter, r *http.Request) {
	var request objectRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	stat, err := handler.storageService.StatObject(
		r.Context(),
		domain.ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey},
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]any{
		"bucket":       stat.Bucket,
		"object_key":   stat.ObjectKey,
		"size":         stat.Size,
		"etag":         stat.ETag,
		"content_type": stat.ContentType,
		"metadata":     stat.Metadata,
	})
}

func (handler *Handler) HandleDeleteObject(w http.ResponseWriter, r *http.Request) {
	var request objectRequest
	if !sharedhttp.DecodeJSON(w, r, &request, sharedhttp.DefaultJSONBodyLimit) {
		return
	}

	err := handler.storageService.DeleteObject(
		r.Context(),
		domain.ObjectRef{Bucket: request.Bucket, ObjectKey: request.ObjectKey},
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}

func (handler *Handler) HandleGetObject(w http.ResponseWriter, r *http.Request) {
	bucket, objectKey, ok := parseObjectPath(r.URL.Path)
	if !ok {
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusCommonInvalidArgument, "对象路径无效", "invalid_object_path")
		return
	}

	stream, err := handler.storageService.GetObject(
		r.Context(),
		domain.ObjectRef{Bucket: bucket, ObjectKey: objectKey},
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}
	defer stream.Body.Close()

	if stream.ContentType != "" {
		w.Header().Set("Content-Type", stream.ContentType)
	}
	if stream.Size >= 0 {
		w.Header().Set("Content-Length", strconv.FormatInt(stream.Size, 10))
	}
	if stream.ETag != "" {
		w.Header().Set("ETag", `"`+strings.Trim(stream.ETag, `"`)+`"`)
	}
	w.WriteHeader(http.StatusOK)
	if _, err := io.Copy(w, stream.Body); err != nil {
		return
	}
}

func (handler *Handler) HandlePutObject(w http.ResponseWriter, r *http.Request) {
	bucket, objectKey, ok := parseObjectPath(r.URL.Path)
	if !ok {
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusCommonInvalidArgument, "对象路径无效", "invalid_object_path")
		return
	}

	body, contentLength, err := seekableBody(http.MaxBytesReader(w, r.Body, handler.maxUploadBodyBytes))
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusUploadFileTooLarge, "上传对象过大", "upload_file_too_large")
			return
		}
		sharedhttp.WriteTransportError(w, http.StatusInternalServerError, sharedhttp.InternalStatusTransportInternalError, "服务内部错误", "temporary_file_error")
		return
	}
	defer func() {
		name := body.Name()
		_ = body.Close()
		_ = os.Remove(name)
	}()

	result, err := handler.storageService.PutObject(
		r.Context(),
		appstorage.PutObjectInput{
			Bucket:        bucket,
			ObjectKey:     objectKey,
			Body:          body,
			ContentLength: contentLength,
			ContentType:   r.Header.Get("Content-Type"),
		},
	)
	if err != nil {
		writeServiceError(w, err)
		return
	}

	sharedhttp.WriteJSON(w, http.StatusOK, map[string]any{
		"bucket":     result.Bucket,
		"object_key": result.ObjectKey,
		"etag":       result.ETag,
	})
}

func parseObjectPath(path string) (string, string, bool) {
	trimmed := strings.TrimPrefix(path, "/objects/")
	parts := strings.SplitN(trimmed, "/", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", "", false
	}
	return parts[0], parts[1], true
}

func writeServiceError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, domain.ErrBucketRequired),
		errors.Is(err, domain.ErrObjectKeyRequired),
		errors.Is(err, domain.ErrInvalidPartCount),
		errors.Is(err, domain.ErrMultipartPartsRequired),
		errors.Is(err, domain.ErrUploadIDRequired):
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusCommonInvalidArgument, "存储请求参数无效", "invalid_storage_argument")
	case errors.Is(err, domain.ErrObjectNotFound):
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusCommonResourceNotFound, "对象不存在", "object_not_found")
	default:
		sharedhttp.WriteBusinessError(w, sharedhttp.InternalStatusStorageUnavailable, "对象存储暂不可用", "storage_unavailable")
	}
}
