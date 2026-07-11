package auth

const (
	// AuthResultPublic marks routes that do not require API-key authentication.
	AuthResultPublic = "public"
	// AuthResultFingerprintReady means the Bearer value passed gateway format
	// checks and was fingerprinted. The backend remains authorization authority.
	AuthResultFingerprintReady = "fingerprint_ready"
	// AuthResultMissingAPIKey marks protected requests without a bearer token.
	AuthResultMissingAPIKey = "missing_api_key"
	// AuthResultInvalidAPIKey marks protected requests with an invalid API key.
	AuthResultInvalidAPIKey = "invalid_api_key"
)
