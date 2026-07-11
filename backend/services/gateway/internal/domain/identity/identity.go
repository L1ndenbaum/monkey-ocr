package identity

// Identity is the authenticated caller identity forwarded to upstream services.
type Identity struct {
	APIKeyFingerprint string
}
