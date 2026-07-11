package envconfig

import (
	"reflect"
	"testing"
	"time"
)

func TestStringReturnsTrimmedValueOrFallback(t *testing.T) {
	t.Setenv("SERVICE_NAME", "  storage  ")

	if got := String("SERVICE_NAME", "fallback"); got != "storage" {
		t.Fatalf("unexpected value %q", got)
	}
	if got := String("MISSING_SERVICE_NAME", "fallback"); got != "fallback" {
		t.Fatalf("unexpected fallback %q", got)
	}
}

func TestDurationAcceptsUnitsAndPositiveSeconds(t *testing.T) {
	t.Setenv("WITH_UNITS", "1500ms")
	t.Setenv("SECONDS", "7")
	t.Setenv("INVALID", "-1s")

	if got := Duration("WITH_UNITS", time.Second); got != 1500*time.Millisecond {
		t.Fatalf("unexpected duration %s", got)
	}
	if got := Duration("SECONDS", time.Second); got != 7*time.Second {
		t.Fatalf("unexpected seconds duration %s", got)
	}
	if got := Duration("INVALID", time.Second); got != time.Second {
		t.Fatalf("unexpected fallback %s", got)
	}
}

func TestIntegerHelpersBoolAndCSV(t *testing.T) {
	t.Setenv("INT_VALUE", "42")
	t.Setenv("INT64_VALUE", "4096")
	t.Setenv("BOOL_VALUE", "yes")
	t.Setenv("CSV_VALUE", " kafka-a:9092, ,kafka-b:9092 ")

	if got := Int("INT_VALUE", 1); got != 42 {
		t.Fatalf("unexpected int %d", got)
	}
	if got := Int64("INT64_VALUE", 1); got != 4096 {
		t.Fatalf("unexpected int64 %d", got)
	}
	if !Bool("BOOL_VALUE", false) {
		t.Fatal("expected bool helper to parse yes as true")
	}
	if got := CSV("CSV_VALUE", "fallback"); !reflect.DeepEqual(got, []string{"kafka-a:9092", "kafka-b:9092"}) {
		t.Fatalf("unexpected csv %#v", got)
	}
}
