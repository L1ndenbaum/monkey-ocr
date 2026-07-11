package headers

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClientIPPrefersNginxRealIPOverSpoofableForwardedChain(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "10.0.0.1:12345"
	request.Header.Set(HeaderXForwardedFor, "198.51.100.7, 10.0.0.10")
	request.Header.Set(HeaderXRealIP, "203.0.113.9")

	if got := ClientIP(request); got != "203.0.113.9" {
		t.Fatalf("client ip = %q, want Nginx real-ip value", got)
	}
}

func TestClientIPFallsBackToRealIP(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "10.0.0.1:12345"
	request.Header.Set(HeaderXRealIP, "203.0.113.9")

	if got := ClientIP(request); got != "203.0.113.9" {
		t.Fatalf("client ip = %q, want real-ip value", got)
	}
}

func TestClientIPUsesNearestForwardedHopWithoutRealIP(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "10.0.0.1:12345"
	request.Header.Set(HeaderXForwardedFor, "198.51.100.7, 203.0.113.9")

	if got := ClientIP(request); got != "203.0.113.9" {
		t.Fatalf("client ip = %q, want nearest forwarded hop", got)
	}
}

func TestClientIPFallsBackToRemoteAddrHost(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "192.0.2.8:4444"

	if got := ClientIP(request); got != "192.0.2.8" {
		t.Fatalf("client ip = %q, want remote host", got)
	}
}

func TestClientIPReturnsTrimmedRemoteAddrWhenHostPortIsInvalid(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = " 192.0.2.8 "

	if got := ClientIP(request); got != "192.0.2.8" {
		t.Fatalf("client ip = %q, want trimmed remote addr", got)
	}
}
