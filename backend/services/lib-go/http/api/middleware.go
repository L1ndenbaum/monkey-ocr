package api

import (
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"strings"
	"time"

	sharedheaders "monkeyocr-services-lib-go/http/headers"
)

// TokenAuthConfig defines shared service-token authentication behavior.
type TokenAuthConfig struct {
	Header          string
	Token           string
	Message         string
	AllowEmptyToken bool
}

// TokenAuth validates a shared service-token header before continuing the route.
func TokenAuth(cfg TokenAuthConfig) func(http.Handler) http.Handler {
	message := cfg.Message
	if message == "" {
		message = "unauthorized"
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if cfg.Token == "" {
				if cfg.AllowEmptyToken {
					next.ServeHTTP(w, r)
					return
				}
				WriteTransportError(w, http.StatusInternalServerError, InternalStatusTransportInternalError, "服务认证未配置", "service_auth_not_configured")
				return
			}
			if r.Header.Get(cfg.Header) != cfg.Token {
				WriteBusinessError(w, InternalStatusUserUnauthorized, message, "service_unauthorized")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// RequestID ensures every service response and downstream call shares one safe
// correlation identifier.
func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestID := strings.TrimSpace(r.Header.Get(sharedheaders.HeaderXRequestID))
		if requestID == "" || strings.ContainsAny(requestID, "\r\n") {
			requestID = generateRequestID()
		}
		r.Header.Set(sharedheaders.HeaderXRequestID, requestID)
		w.Header().Set(sharedheaders.HeaderXRequestID, requestID)
		next.ServeHTTP(w, r)
	})
}

// Recovery converts an unhandled panic into the only permitted origin-side
// transport failure response.
func Recovery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recover() != nil {
				WriteTransportError(w, http.StatusInternalServerError, InternalStatusTransportInternalError, "服务内部错误", "transport_internal_error")
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func generateRequestID() string {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return time.Now().UTC().Format("20060102T150405.000000000")
	}
	return hex.EncodeToString(raw)
}
