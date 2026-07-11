package server

import (
	"net/http"
	"testing"
	"time"
)

func TestNewUsesConfiguredAddressHandlerAndTimeouts(t *testing.T) {
	handler := http.NewServeMux()
	cfg := Config{
		Addr:              ":9090",
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       3 * time.Second,
		WriteTimeout:      4 * time.Second,
		IdleTimeout:       5 * time.Second,
	}

	server := New(cfg, handler)

	if server.Addr != cfg.Addr {
		t.Fatalf("unexpected addr: %s", server.Addr)
	}
	if server.Handler != handler {
		t.Fatal("server should use the provided handler")
	}
	if server.ReadHeaderTimeout != cfg.ReadHeaderTimeout {
		t.Fatalf("unexpected read header timeout: %s", server.ReadHeaderTimeout)
	}
	if server.ReadTimeout != cfg.ReadTimeout {
		t.Fatalf("unexpected read timeout: %s", server.ReadTimeout)
	}
	if server.WriteTimeout != cfg.WriteTimeout {
		t.Fatalf("unexpected write timeout: %s", server.WriteTimeout)
	}
	if server.IdleTimeout != cfg.IdleTimeout {
		t.Fatalf("unexpected idle timeout: %s", server.IdleTimeout)
	}
}
