package pipeline

import (
	"net/http"
)

// HandleHealth handles the gateway-local health endpoint.
func (pipeline *Pipeline) HandleHealth(recorder ResponseStatusRecorder, r *http.Request) {
	pipeline.runGatewayStages(recorder, r, pipeline.healthResponseStage)
}

// HandleProxy handles upstream gateway requests.
func (pipeline *Pipeline) HandleProxy(recorder ResponseStatusRecorder, r *http.Request) {
	pipeline.runGatewayStages(
		recorder,
		r,
		pipeline.clientIPRateLimitStage,
		pipeline.authenticationStage,
		pipeline.apiKeyRateLimitStage,
		pipeline.serviceRateLimitStage,
		pipeline.identityHeaderStage,
		pipeline.proxyStage,
	)
}
