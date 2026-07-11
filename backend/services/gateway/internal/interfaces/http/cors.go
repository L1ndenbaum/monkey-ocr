package httpapi

import (
	"net/http"
	"strings"
)

const (
	corsAllowMethods = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
	corsAllowHeaders = "Authorization,Content-Type,X-Request-ID"
)

// CORSConfig controls gateway-owned browser CORS handling.
type CORSConfig struct {
	AllowedOrigins      []string
	MaxRequestBodyBytes int64
}

func corsMiddleware(config CORSConfig) func(http.Handler) http.Handler {
	allowedOrigins := make(map[string]struct{}, len(config.AllowedOrigins))
	for _, origin := range config.AllowedOrigins {
		origin = strings.TrimSpace(origin)
		if origin != "" {
			allowedOrigins[origin] = struct{}{}
		}
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := strings.TrimSpace(r.Header.Get("Origin"))
			if _, allowed := allowedOrigins[origin]; !allowed {
				next.ServeHTTP(w, r)
				return
			}

			header := w.Header()
			header.Set("Access-Control-Allow-Origin", origin)
			header.Add("Vary", "Origin")
			header.Set("Access-Control-Allow-Credentials", "true")
			header.Set("Access-Control-Allow-Methods", corsAllowMethods)
			requestHeaders := strings.TrimSpace(r.Header.Get("Access-Control-Request-Headers"))
			if requestHeaders == "" {
				requestHeaders = corsAllowHeaders
			}
			header.Set("Access-Control-Allow-Headers", requestHeaders)

			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusOK)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}
