package pipeline

import (
	domain2 "monkeyocr-gateway/internal/domain/identity"
	"testing"
)

func equalStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func TestRunStageChainStopsAfterFailedStage(t *testing.T) {
	calls := []string{}
	gatewayContext := &GatewayContext{}

	completed := runStageChain(
		gatewayContext,
		func(ctx *GatewayContext) bool {
			calls = append(calls, "first")
			ctx.Identity = &domain2.Identity{APIKeyFingerprint: "user-1"}
			return true
		},
		func(ctx *GatewayContext) bool {
			calls = append(calls, "stop")
			return false
		},
		func(ctx *GatewayContext) bool {
			calls = append(calls, "after-stop")
			return true
		},
	)

	if completed {
		t.Fatal("stage chain should report incomplete when a stage stops the chain")
	}
	if !equalStrings(calls, []string{"first", "stop"}) {
		t.Fatalf("stage calls = %#v, want first and stop only", calls)
	}
	if gatewayContext.Identity == nil || gatewayContext.Identity.APIKeyFingerprint != "user-1" {
		t.Fatalf("stage did not share gateway context identity: %#v", gatewayContext.Identity)
	}
}

func TestRunStageChainCompletesAllStages(t *testing.T) {
	calls := []string{}
	gatewayContext := &GatewayContext{}

	completed := runStageChain(
		gatewayContext,
		func(_ *GatewayContext) bool {
			calls = append(calls, "first")
			return true
		},
		func(_ *GatewayContext) bool {
			calls = append(calls, "second")
			return true
		},
	)

	if !completed {
		t.Fatal("stage chain should report complete when all stages continue")
	}
	if !equalStrings(calls, []string{"first", "second"}) {
		t.Fatalf("stage calls = %#v, want both stages", calls)
	}
}
