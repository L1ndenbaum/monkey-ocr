package config

import (
	"testing"
	"time"
)

func TestLoadReadsHTTPTimeoutsAndUploadLimit(t *testing.T) {
	t.Setenv("STORAGE_SERVICE_READ_HEADER_TIMEOUT", "3s")
	t.Setenv("STORAGE_SERVICE_READ_TIMEOUT", "11s")
	t.Setenv("STORAGE_SERVICE_WRITE_TIMEOUT", "22s")
	t.Setenv("STORAGE_SERVICE_IDLE_TIMEOUT", "33s")
	t.Setenv("STORAGE_SERVICE_MAX_UPLOAD_BYTES", "4096")

	cfg := Load()

	if cfg.ReadHeaderTimeout != 3*time.Second {
		t.Fatalf("unexpected read header timeout: %s", cfg.ReadHeaderTimeout)
	}
	if cfg.ReadTimeout != 11*time.Second {
		t.Fatalf("unexpected read timeout: %s", cfg.ReadTimeout)
	}
	if cfg.WriteTimeout != 22*time.Second {
		t.Fatalf("unexpected write timeout: %s", cfg.WriteTimeout)
	}
	if cfg.IdleTimeout != 33*time.Second {
		t.Fatalf("unexpected idle timeout: %s", cfg.IdleTimeout)
	}
	if cfg.MaxUploadBodyBytes != 4096 {
		t.Fatalf("unexpected max upload bytes: %d", cfg.MaxUploadBodyBytes)
	}
}

func TestLoadUsesSafeHTTPDefaults(t *testing.T) {
	cfg := Load()

	if cfg.ReadHeaderTimeout <= 0 {
		t.Fatal("read header timeout must be enabled")
	}
	if cfg.ReadTimeout <= 0 {
		t.Fatal("read timeout must be enabled")
	}
	if cfg.WriteTimeout <= 0 {
		t.Fatal("write timeout must be enabled")
	}
	if cfg.IdleTimeout <= 0 {
		t.Fatal("idle timeout must be enabled")
	}
	if cfg.MaxUploadBodyBytes <= 0 {
		t.Fatal("max upload bytes must be enabled")
	}
}
