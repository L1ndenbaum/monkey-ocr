package rate_limit

// RateLimitScope names the gateway limit dimension being checked.
type RateLimitScope string

const (
	// RateLimitScopeClientIP protects the gateway by caller network address.
	RateLimitScopeClientIP RateLimitScope = "client_ip"
	// RateLimitScopeAPIKey protects the gateway by authenticated API key id.
	RateLimitScopeAPIKey RateLimitScope = "api_key"
	// RateLimitScopeService protects one internal upstream service.
	RateLimitScopeService RateLimitScope = "service"
)

// RateLimitTarget identifies the key consumed by one limiter scope.
type RateLimitTarget struct {
	Scope RateLimitScope
	Key   string
}

// RateLimitDecision is the normalized result returned by rate limit backends.
type RateLimitDecision struct {
	Allowed      bool
	Result       string
	RejectReason string
}
