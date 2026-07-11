package s3storage

import (
	"testing"

	smithy "github.com/aws/smithy-go"
)

type apiErrorStub struct {
	code string
}

func (err apiErrorStub) Error() string                 { return err.code }
func (err apiErrorStub) ErrorCode() string             { return err.code }
func (err apiErrorStub) ErrorMessage() string          { return err.code }
func (err apiErrorStub) ErrorFault() smithy.ErrorFault { return smithy.FaultClient }

func TestIsNoSuchUpload(t *testing.T) {
	if !isNoSuchUpload(apiErrorStub{code: "NoSuchUpload"}) {
		t.Fatal("NoSuchUpload must be treated as an idempotent abort")
	}
	if isNoSuchUpload(apiErrorStub{code: "AccessDenied"}) {
		t.Fatal("storage authorization failures must not be ignored")
	}
}
