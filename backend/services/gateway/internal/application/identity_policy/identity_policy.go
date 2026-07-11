package identity_policy

import (
	"monkeyocr-gateway/internal/domain/identity"
	"net/http"
	"strings"

	sharedheaders "monkeyocr-services-lib-go/http/headers"
)

const (
	apiKeyFingerprintHeader = sharedheaders.HeaderXAPIKeyFingerprint
)

// IdentityPolicy sanitizes caller-supplied identity headers and forwards trusted identity.
type IdentityPolicy struct{}

// Apply clears spoofable identity headers and injects authenticated identity when present.
func (policy IdentityPolicy) Apply(header http.Header, identity *identity.Identity) {
	header.Del(apiKeyFingerprintHeader)
	if identity == nil {
		return
	}
	if strings.TrimSpace(identity.APIKeyFingerprint) != "" {
		header.Set(apiKeyFingerprintHeader, identity.APIKeyFingerprint)
	}
}
