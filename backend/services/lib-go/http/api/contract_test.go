package api

import "testing"

func TestParseEnvelopeRejectsBareDTOAndLegacyCode(t *testing.T) {
	for _, body := range []string{
		`{"accepted":1}`,
		`{"code":0,"internal_code":0,"message":"ok","data":{},"timestamp":"2026-07-11T00:00:00Z","request_id":"req","error_reason":null}`,
	} {
		if _, err := ParseEnvelope([]byte(body)); err == nil {
			t.Fatalf("ParseEnvelope(%s) succeeded", body)
		}
	}
}

func TestParseEnvelopeAcceptsCurrentContract(t *testing.T) {
	body := `{"internal_code":0,"message":"ok","data":{},"timestamp":"2026-07-11T00:00:00Z","request_id":"req","error_reason":null}`
	if _, err := ParseEnvelope([]byte(body)); err != nil {
		t.Fatalf("ParseEnvelope: %v", err)
	}
}
