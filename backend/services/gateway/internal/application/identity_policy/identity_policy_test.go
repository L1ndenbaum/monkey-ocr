package identity_policy

import (
	"monkeyocr-gateway/internal/domain/identity"
	"net/http"
	"testing"
)

func TestIdentityPolicyClearsSpoofedIdentityHeadersForPublicRequests(t *testing.T) {
	header := http.Header{}
	header.Set("X-API-Key-Fingerprint", "attacker")

	IdentityPolicy{}.Apply(header, nil)

	if got := header.Get("X-API-Key-Fingerprint"); got != "" {
		t.Fatalf("X-API-Key-Fingerprint = %q, want cleared", got)
	}
}

func TestIdentityPolicyForwardsAuthenticatedIdentity(t *testing.T) {
	header := http.Header{}
	identity := &identity.Identity{APIKeyFingerprint: "key-1"}

	IdentityPolicy{}.Apply(header, identity)

	if got := header.Get("X-API-Key-Fingerprint"); got != "key-1" {
		t.Fatalf("X-API-Key-Fingerprint = %q, want key-1", got)
	}
}
