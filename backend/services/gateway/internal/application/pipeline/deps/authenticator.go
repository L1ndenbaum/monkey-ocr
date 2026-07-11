package deps

import (
	"context"
	domain2 "monkeyocr-gateway/internal/domain/identity"
)

// Authenticator validates bearer tokens and returns an upstream identity.
type Authenticator interface {
	Authenticate(context.Context, string) (domain2.Identity, error)
}
