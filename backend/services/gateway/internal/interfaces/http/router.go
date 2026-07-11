package httpapi

import (
	"bytes"
	"io"
	"net/http"

	"github.com/go-chi/chi/v5"
	sharedapi "monkeyocr-services-lib-go/http/api"
)

// NewRouter builds the chi gateway router with local health and upstream routes.
func NewRouter(handler *Handler, corsConfig CORSConfig) http.Handler {
	router := chi.NewRouter()
	router.Use(sharedapi.RequestID)
	router.Use(sharedapi.Recovery)
	router.Use(corsMiddleware(corsConfig))
	router.Use(requestBodyLimit(corsConfig.MaxRequestBodyBytes))
	router.Get("/health", handler.HandleHealth)
	router.Handle("/*", http.HandlerFunc(handler.HandleProxy))
	return router
}

func requestBodyLimit(limit int64) func(http.Handler) http.Handler {
	if limit <= 0 {
		limit = 1 << 20
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Body == nil || r.Body == http.NoBody {
				next.ServeHTTP(w, r)
				return
			}
			body, err := io.ReadAll(io.LimitReader(r.Body, limit+1))
			_ = r.Body.Close()
			if err != nil {
				sharedapi.WriteBusinessError(w, sharedapi.InternalStatusCommonInvalidArgument, "请求体无效", "invalid_request_body")
				return
			}
			if int64(len(body)) > limit {
				sharedapi.WriteBusinessError(w, sharedapi.InternalStatusUploadFileTooLarge, "请求体过大", "request_body_too_large")
				return
			}
			r.Body = io.NopCloser(bytes.NewReader(body))
			r.ContentLength = int64(len(body))
			next.ServeHTTP(w, r)
		})
	}
}
