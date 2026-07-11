// Code generated from backend/contracts/internal_status_codes.json; DO NOT EDIT.
package api

type InternalStatusCode int

const (
	InternalStatusSuccess                   InternalStatusCode = 0
	InternalStatusCommonInvalidArgument     InternalStatusCode = 10001
	InternalStatusCommonResourceNotFound    InternalStatusCode = 10002
	InternalStatusCommonStateConflict       InternalStatusCode = 10003
	InternalStatusCommonIdempotencyConflict InternalStatusCode = 10004
	InternalStatusUploadNotFound            InternalStatusCode = 20001
	InternalStatusUploadNotCompleted        InternalStatusCode = 20002
	InternalStatusUploadHashMismatch        InternalStatusCode = 20003
	InternalStatusUploadUnsupportedFileType InternalStatusCode = 20004
	InternalStatusUploadFileTooLarge        InternalStatusCode = 20005
	InternalStatusUploadSecurityRejected    InternalStatusCode = 20006
	InternalStatusJobNotFound               InternalStatusCode = 30001
	InternalStatusJobNotCancellable         InternalStatusCode = 30002
	InternalStatusJobNotRetryable           InternalStatusCode = 30003
	InternalStatusJobProcessingFailed       InternalStatusCode = 30004
	InternalStatusJobResultNotReady         InternalStatusCode = 30005
	InternalStatusUserUnauthorized          InternalStatusCode = 40001
	InternalStatusAPIKeyRevoked             InternalStatusCode = 40002
	InternalStatusAPIKeyRateLimited         InternalStatusCode = 40003
	InternalStatusEngineUnavailable         InternalStatusCode = 50001
	InternalStatusEngineTimeout             InternalStatusCode = 50002
	InternalStatusStorageUnavailable        InternalStatusCode = 50003
	InternalStatusQueueUnavailable          InternalStatusCode = 50004
	InternalStatusDatabaseUnavailable       InternalStatusCode = 50005
	InternalStatusInternalControlledError   InternalStatusCode = 59999
	InternalStatusTransportInternalError    InternalStatusCode = 90000
	InternalStatusTransportBadGateway       InternalStatusCode = 90002
	InternalStatusTransportGatewayTimeout   InternalStatusCode = 90004
)

// String returns the stable cross-language enum name used in structured logs.
func (code InternalStatusCode) String() string {
	switch code {
	case InternalStatusSuccess:
		return "SUCCESS"
	case InternalStatusCommonInvalidArgument:
		return "COMMON_INVALID_ARGUMENT"
	case InternalStatusCommonResourceNotFound:
		return "COMMON_RESOURCE_NOT_FOUND"
	case InternalStatusCommonStateConflict:
		return "COMMON_STATE_CONFLICT"
	case InternalStatusCommonIdempotencyConflict:
		return "COMMON_IDEMPOTENCY_CONFLICT"
	case InternalStatusUploadNotFound:
		return "UPLOAD_NOT_FOUND"
	case InternalStatusUploadNotCompleted:
		return "UPLOAD_NOT_COMPLETED"
	case InternalStatusUploadHashMismatch:
		return "UPLOAD_HASH_MISMATCH"
	case InternalStatusUploadUnsupportedFileType:
		return "UPLOAD_UNSUPPORTED_FILE_TYPE"
	case InternalStatusUploadFileTooLarge:
		return "UPLOAD_FILE_TOO_LARGE"
	case InternalStatusUploadSecurityRejected:
		return "UPLOAD_SECURITY_REJECTED"
	case InternalStatusJobNotFound:
		return "JOB_NOT_FOUND"
	case InternalStatusJobNotCancellable:
		return "JOB_NOT_CANCELLABLE"
	case InternalStatusJobNotRetryable:
		return "JOB_NOT_RETRYABLE"
	case InternalStatusJobProcessingFailed:
		return "JOB_PROCESSING_FAILED"
	case InternalStatusJobResultNotReady:
		return "JOB_RESULT_NOT_READY"
	case InternalStatusUserUnauthorized:
		return "USER_UNAUTHORIZED"
	case InternalStatusAPIKeyRevoked:
		return "API_KEY_REVOKED"
	case InternalStatusAPIKeyRateLimited:
		return "API_KEY_RATE_LIMITED"
	case InternalStatusEngineUnavailable:
		return "ENGINE_UNAVAILABLE"
	case InternalStatusEngineTimeout:
		return "ENGINE_TIMEOUT"
	case InternalStatusStorageUnavailable:
		return "STORAGE_UNAVAILABLE"
	case InternalStatusQueueUnavailable:
		return "QUEUE_UNAVAILABLE"
	case InternalStatusDatabaseUnavailable:
		return "DATABASE_UNAVAILABLE"
	case InternalStatusInternalControlledError:
		return "INTERNAL_CONTROLLED_ERROR"
	case InternalStatusTransportInternalError:
		return "TRANSPORT_INTERNAL_ERROR"
	case InternalStatusTransportBadGateway:
		return "TRANSPORT_BAD_GATEWAY"
	case InternalStatusTransportGatewayTimeout:
		return "TRANSPORT_GATEWAY_TIMEOUT"
	default:
		return "UNKNOWN"
	}
}
