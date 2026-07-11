package apikey

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"unicode"

	"monkeyocr-gateway/internal/domain/identity"
)

var ErrInvalidAPIKey = errors.New("invalid API key")

// Validator permits replacing the local hash list with a backend or dedicated
// credential-store validator without changing the gateway pipeline.
type Validator interface {
	Validate(context.Context, string) (string, error)
}

// Authenticator adapts an API-key validator to the gateway authentication port.
type Authenticator struct {
	validator Validator
}

func NewAuthenticator(validator Validator) *Authenticator {
	return &Authenticator{validator: validator}
}

func (authenticator *Authenticator) Authenticate(ctx context.Context, token string) (identity.Identity, error) {
	if authenticator == nil || token == "" || len(token) > 512 || strings.IndexFunc(token, unicode.IsSpace) >= 0 {
		return identity.Identity{}, ErrInvalidAPIKey
	}
	if authenticator.validator != nil {
		if _, err := authenticator.validator.Validate(ctx, token); err != nil {
			return identity.Identity{}, ErrInvalidAPIKey
		}
	}
	digest := sha256.Sum256([]byte(token))
	return identity.Identity{APIKeyFingerprint: hex.EncodeToString(digest[:])}, nil
}

type hashRecord struct {
	id     string
	digest [sha256.Size]byte
}

// StaticSHA256Validator is an optional emergency restriction. PostgreSQL in
// the backend remains authoritative for API-key validity and revocation. It
// verifies keys against entries in the form
// "key-id=<64 lowercase or uppercase hex characters>". Only hashes are loaded;
// plaintext keys are never accepted as configuration.
type StaticSHA256Validator struct {
	records []hashRecord
}

func NewStaticSHA256Validator(entries []string) (*StaticSHA256Validator, error) {
	records := make([]hashRecord, 0, len(entries))
	seen := make(map[string]struct{}, len(entries))
	for _, entry := range entries {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		keyID, encoded, ok := strings.Cut(entry, "=")
		keyID = strings.TrimSpace(keyID)
		encoded = strings.TrimSpace(encoded)
		if !ok || keyID == "" {
			return nil, fmt.Errorf("invalid API key hash entry")
		}
		if _, exists := seen[keyID]; exists {
			return nil, fmt.Errorf("duplicate API key id %q", keyID)
		}
		raw, err := hex.DecodeString(encoded)
		if err != nil || len(raw) != sha256.Size {
			return nil, fmt.Errorf("invalid SHA-256 digest for API key id %q", keyID)
		}
		var digest [sha256.Size]byte
		copy(digest[:], raw)
		records = append(records, hashRecord{id: keyID, digest: digest})
		seen[keyID] = struct{}{}
	}
	return &StaticSHA256Validator{records: records}, nil
}

func (validator *StaticSHA256Validator) Validate(_ context.Context, token string) (string, error) {
	if validator == nil || token == "" {
		return "", ErrInvalidAPIKey
	}
	digest := sha256.Sum256([]byte(token))
	matchedID := ""
	for _, record := range validator.records {
		if subtle.ConstantTimeCompare(digest[:], record.digest[:]) == 1 {
			matchedID = record.id
		}
	}
	if matchedID == "" {
		return "", ErrInvalidAPIKey
	}
	return matchedID, nil
}
