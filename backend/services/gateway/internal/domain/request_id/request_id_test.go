package request_id

import "testing"

func TestRequestIDPolicyReusesSafeInboundValue(t *testing.T) {
	policy := RequestIDPolicy{}

	if got := policy.Resolve(" req-123 "); got != "req-123" {
		t.Fatalf("request id = %q, want req-123", got)
	}
}

func TestRequestIDPolicyRejectsHeaderInjection(t *testing.T) {
	policy := RequestIDPolicy{}

	got := policy.Resolve("bad\r\nX-User-ID: admin")
	if got == "" || got == "bad\r\nX-User-ID: admin" {
		t.Fatalf("request id = %q, want generated safe value", got)
	}
}
