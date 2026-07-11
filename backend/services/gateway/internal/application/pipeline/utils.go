package pipeline

import (
	"net/http"
	"strings"

	sharedhttp "monkeyocr-services-lib-go/http/api"
)

func classifyUserAgentType(value string) string {
	lower := strings.ToLower(value)
	switch {
	case lower == "":
		return "unknown"
	case strings.Contains(lower, "bot") || strings.Contains(lower, "spider") || strings.Contains(lower, "crawler"):
		return "crawler"
	case strings.Contains(lower, "postman") || strings.Contains(lower, "insomnia") || strings.Contains(lower, "apifox"):
		return "api_testing_tool"
	case strings.Contains(lower, "curl") || strings.Contains(lower, "wget") || strings.Contains(lower, "python-requests") || strings.Contains(lower, "httpie"):
		return "script"
	case strings.Contains(lower, "mobile") || strings.Contains(lower, "okhttp") || strings.Contains(lower, "cfnetwork"):
		return "mobile_app"
	case strings.Contains(lower, "mozilla") || strings.Contains(lower, "chrome") || strings.Contains(lower, "safari") || strings.Contains(lower, "firefox"):
		return "browser"
	default:
		return "unknown"
	}
}

// writeJSON writes the gateway-local ApiEnvelope response.
func writeJSON(w http.ResponseWriter, status int, payload any) {
	if status >= http.StatusBadRequest {
		sharedhttp.WriteError(w, status, messageFromPayload(payload))
		return
	}
	sharedhttp.WriteJSON(w, status, payload)
}

func writeBusinessError(gatewayContext *GatewayContext, internalCode sharedhttp.InternalStatusCode, message, reason string) {
	gatewayContext.Metadata.InternalCode = int(internalCode)
	gatewayContext.Metadata.InternalStatusName = internalStatusName(internalCode)
	sharedhttp.WriteBusinessError(gatewayContext.Recorder, internalCode, message, reason)
}

func internalStatusName(internalCode sharedhttp.InternalStatusCode) string {
	return internalCode.String()
}

// messageFromPayload extracts a stable error message from local response data.
func messageFromPayload(payload any) string {
	switch body := payload.(type) {
	case map[string]string:
		if message := body["message"]; message != "" {
			return message
		}
	case map[string]any:
		if message, ok := body["message"].(string); ok && message != "" {
			return message
		}
	}
	return "请求失败"
}
