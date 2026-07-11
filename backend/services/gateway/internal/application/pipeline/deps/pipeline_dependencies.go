package deps

// PipelineDependencies are side-effecting collaborators used by Pipeline.
type PipelineDependencies struct {
	Authenticator   Authenticator
	ClientIPLimiter ClientIPLimiter
	APIKeyLimiter   APIKeyLimiter
	ServiceLimiter  ServiceLimiter
	Proxy           UpstreamProxy
	AccessLogger    AccessLogger
}
