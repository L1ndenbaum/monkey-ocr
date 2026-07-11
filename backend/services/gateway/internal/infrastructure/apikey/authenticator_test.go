package apikey

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func TestStaticSHA256ValidatorAuthenticatesConfiguredHash(t *testing.T) {
	digest := sha256.Sum256([]byte("test-secret"))
	validator, err := NewStaticSHA256Validator([]string{"key-1=" + hex.EncodeToString(digest[:])})
	if err != nil {
		t.Fatalf("NewStaticSHA256Validator: %v", err)
	}
	authenticator := NewAuthenticator(validator)

	got, err := authenticator.Authenticate(context.Background(), "test-secret")
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	if got.APIKeyFingerprint != hex.EncodeToString(digest[:]) {
		t.Fatalf("APIKeyFingerprint = %q, want SHA-256 fingerprint", got.APIKeyFingerprint)
	}
}

func TestAuthenticatorWithoutEmergencyAllowlistDefersAuthorityToBackend(t *testing.T) {
	digest := sha256.Sum256([]byte("backend-validates-this"))
	got, err := NewAuthenticator(nil).Authenticate(context.Background(), "backend-validates-this")
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	if got.APIKeyFingerprint != hex.EncodeToString(digest[:]) {
		t.Fatalf("APIKeyFingerprint = %q", got.APIKeyFingerprint)
	}
}

func TestStaticSHA256ValidatorRejectsPlaintextConfiguration(t *testing.T) {
	if _, err := NewStaticSHA256Validator([]string{"key-1=test-secret"}); err == nil {
		t.Fatal("expected plaintext configuration to be rejected")
	}
}

func TestStaticSHA256ValidatorRejectsUnknownKey(t *testing.T) {
	digest := sha256.Sum256([]byte("test-secret"))
	validator, err := NewStaticSHA256Validator([]string{"key-1=" + hex.EncodeToString(digest[:])})
	if err != nil {
		t.Fatalf("NewStaticSHA256Validator: %v", err)
	}

	if _, err := NewAuthenticator(validator).Authenticate(context.Background(), "other-secret"); err == nil {
		t.Fatal("expected unknown key to be rejected")
	}
}
