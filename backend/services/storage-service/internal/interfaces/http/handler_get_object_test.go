package httpapi

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	sharedhttp "monkeyocr-services-lib-go/http/api"
	appstorage "monkeyocr-storage-service/internal/application/storage"
	domain "monkeyocr-storage-service/internal/domain/storage"
)

type fakeObjectRepository struct {
	body   []byte
	getErr error
}

func (repo fakeObjectRepository) EnsureBucket(context.Context, string) error { return nil }
func (repo fakeObjectRepository) CreateMultipartUpload(context.Context, domain.CreateMultipartRequest) (domain.MultipartUpload, error) {
	return domain.MultipartUpload{}, nil
}
func (repo fakeObjectRepository) CompleteMultipartUpload(context.Context, domain.CompleteMultipartRequest) (domain.CompleteMultipartResult, error) {
	return domain.CompleteMultipartResult{}, nil
}
func (repo fakeObjectRepository) AbortMultipartUpload(context.Context, domain.AbortMultipartRequest) error {
	return nil
}
func (repo fakeObjectRepository) PresignGetObject(context.Context, domain.ObjectRef, int) (string, error) {
	return "", nil
}
func (repo fakeObjectRepository) PresignPutObject(context.Context, domain.ObjectRef, string, int) (string, error) {
	return "https://upload.example.com/files/demo-object", nil
}
func (repo fakeObjectRepository) StatObject(context.Context, domain.ObjectRef) (domain.ObjectStat, error) {
	return domain.ObjectStat{}, nil
}
func (repo fakeObjectRepository) DeleteObject(context.Context, domain.ObjectRef) error { return nil }
func (repo fakeObjectRepository) PutObject(context.Context, appstorage.PutObjectInput) (domain.PutObjectResult, error) {
	return domain.PutObjectResult{}, nil
}
func (repo fakeObjectRepository) GetObject(ctx context.Context, ref domain.ObjectRef) (domain.ObjectStream, error) {
	if repo.getErr != nil {
		return domain.ObjectStream{}, repo.getErr
	}
	return domain.ObjectStream{
		Bucket:      ref.Bucket,
		ObjectKey:   ref.ObjectKey,
		Body:        io.NopCloser(strings.NewReader(string(repo.body))),
		Size:        int64(len(repo.body)),
		ETag:        "etag-object",
		ContentType: "image/png",
	}, nil
}

func TestHandleGetObjectStreamsAuthenticatedObject(t *testing.T) {
	service := appstorage.NewService(fakeObjectRepository{body: []byte("image-bytes")})
	router := NewRouter(NewHandler(service, "secret-token"))

	request := httptest.NewRequest(http.MethodGet, "/objects/medical-image-files/path/to/image.png", nil)
	request.Header.Set(storageServiceTokenHeader, "secret-token")
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
	if response.Body.String() != "image-bytes" {
		t.Fatalf("unexpected body %q", response.Body.String())
	}
	if response.Header().Get("Content-Type") != "image/png" {
		t.Fatalf("unexpected content type %q", response.Header().Get("Content-Type"))
	}
	if response.Header().Get("ETag") != `"etag-object"` {
		t.Fatalf("unexpected etag %q", response.Header().Get("ETag"))
	}
}

func TestHandleGetObjectRequiresStorageToken(t *testing.T) {
	service := appstorage.NewService(fakeObjectRepository{body: []byte("image-bytes")})
	router := NewRouter(NewHandler(service, "secret-token"))

	request := httptest.NewRequest(http.MethodGet, "/objects/medical-image-files/path/to/image.png", nil)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"internal_code":40001`) {
		t.Fatalf("unexpected auth response %d %s", response.Code, response.Body.String())
	}
	if response.Header().Get(sharedhttp.InternalCodeHeader) != "40001" {
		t.Fatalf("missing internal-code discriminator header: %v", response.Header())
	}
}

func TestHandleGetObjectMarksNotFoundEnvelopeForRawClient(t *testing.T) {
	service := appstorage.NewService(fakeObjectRepository{getErr: domain.ErrObjectNotFound})
	router := NewRouter(NewHandler(service, "secret-token"))

	request := httptest.NewRequest(http.MethodGet, "/objects/monkeyocr-documents/missing.png", nil)
	request.Header.Set(storageServiceTokenHeader, "secret-token")
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"error_reason":"object_not_found"`) {
		t.Fatalf("unexpected not-found response %d %s", response.Code, response.Body.String())
	}
	if response.Header().Get(sharedhttp.InternalCodeHeader) != "10002" {
		t.Fatalf("missing internal-code discriminator header: %v", response.Header())
	}
}

func TestHandlePresignPutReturnsUploadURL(t *testing.T) {
	service := appstorage.NewService(fakeObjectRepository{body: []byte("image-bytes")})
	router := NewRouter(NewHandler(service, "secret-token"))

	request := httptest.NewRequest(
		http.MethodPost,
		"/presign/put",
		strings.NewReader(`{"bucket":"monkeyocr-documents","object_key":"files/user-1/file-1","content_type":"text/plain","expires_in":600}`),
	)
	request.Header.Set(storageServiceTokenHeader, "secret-token")
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), `"url":"https://upload.example.com/files/demo-object"`) {
		t.Fatalf("unexpected body %s", response.Body.String())
	}
}

func TestHandlePutObjectRejectsBodiesOverLimit(t *testing.T) {
	service := appstorage.NewService(fakeObjectRepository{body: []byte("image-bytes")})
	router := NewRouter(NewHandler(service, "secret-token", WithMaxUploadBodyBytes(4)))

	request := httptest.NewRequest(
		http.MethodPut,
		"/objects/medical-image-files/path/to/image.png",
		strings.NewReader("image-bytes"),
	)
	request.Header.Set(storageServiceTokenHeader, "secret-token")
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"internal_code":20005`) {
		t.Fatalf("unexpected oversized response %d %s", response.Code, response.Body.String())
	}
}
