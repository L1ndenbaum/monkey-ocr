package headers

import (
	"net"
	"net/http"
	"strings"
)

const (
	// HeaderXRequestID is the gateway request-correlation header.
	HeaderXRequestID = "X-Request-ID"
	// HeaderXAPIKeyFingerprint carries a non-secret SHA-256 token fingerprint.
	// It supports rate limiting but is not an authorization verdict.
	HeaderXAPIKeyFingerprint = "X-API-Key-Fingerprint"
	// HeaderXUserID carries the trusted gateway-authenticated user id.
	HeaderXUserID = "X-User-ID"
	// HeaderXUserRoles carries trusted gateway-authenticated user roles.
	HeaderXUserRoles = "X-User-Roles"
	// HeaderXForwardedFor carries the original client IP chain.
	HeaderXForwardedFor = "X-Forwarded-For"
	// HeaderXRealIP carries the direct upstream client IP.
	HeaderXRealIP = "X-Real-IP"
)

// ClientIP extracts the best available caller IP from trusted gateway headers.
func ClientIP(r *http.Request) string {
	// The deployment Nginx overwrites X-Real-IP. Prefer it over X-Forwarded-For,
	// whose left-most entry may be supplied by an untrusted client.
	if realIP := strings.TrimSpace(r.Header.Get(HeaderXRealIP)); realIP != "" {
		return realIP
	}
	if forwardedFor := strings.TrimSpace(r.Header.Get(HeaderXForwardedFor)); forwardedFor != "" {
		parts := strings.Split(forwardedFor, ",")
		if len(parts) > 0 {
			return strings.TrimSpace(parts[len(parts)-1])
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return strings.TrimSpace(r.RemoteAddr)
}
