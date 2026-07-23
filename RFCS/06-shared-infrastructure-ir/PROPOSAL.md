# RFC-06: Shared Infrastructure Intermediate Representation (IIR)

**Status:** Proposal

## Summary

This RFC proposes introducing a **Shared Infrastructure Intermediate
Representation (IIR)** as the canonical semantic model within CDKTN.

The IIR represents infrastructure intent independently of any cloud
provider, deployment engine, serialization format, or programming
language. It establishes a stable contract between construct libraries
and infrastructure backends, allowing both to evolve independently while
sharing the same runtime abstractions.

Unlike backend-specific representations such as CloudFormation templates
or Terraform configuration, the IIR models infrastructure semantics
rather than deployment syntax.

## Motivation

CDKTN has evolved beyond a collection of Terraform synthesis utilities.
Over time it has accumulated reusable abstractions for expressions,
references, provider metadata, dependency graphs, lifecycle information,
serialization, and synthesis. These abstractions are not inherently tied
to AWS or Terraform; they describe common infrastructure concepts.

Historically, these abstractions have primarily been validated through
AWS compatibility work. The introduction of independently developed
Azure construct libraries built on CDKTN demonstrates that these
concepts are broadly applicable. This convergence suggests the need for
a shared semantic representation that both ecosystems can target.

Without such a representation, each construct library risks embedding
backend assumptions or duplicating runtime logic. A shared IIR allows
CDKTN to become a reusable infrastructure runtime rather than a runtime
optimized for a single ecosystem.

## Problem Statement

Today's construct ecosystems typically synthesize directly into
backend-specific representations. This tightly couples construct
semantics to deployment technologies and makes it difficult to introduce
new backends or validate common abstractions across providers.

The absence of a shared semantic layer also complicates testing because
behavior and serialization become intertwined.

## Goals

The objectives are to define a cloud-neutral and backend-neutral
semantic model, provide a stable contract between construct libraries
and runtimes, maximize reuse of CDKTN abstractions, reduce duplication
of translation logic, and enable future backends without requiring
changes to construct APIs.

## Non-Goals

This RFC does not define Terraform syntax, CloudFormation syntax,
provider schemas, deployment workflows, or public APIs. It does not
replace provider-specific construct libraries.

## Design Principles

### Infrastructure Intent

The IIR models infrastructure intent rather than deployment syntax.

### Cloud Neutrality

The model must avoid assumptions specific to AWS, Azure, Google Cloud,
Kubernetes, or future providers.

### Backend Neutrality

The IIR excludes CloudFormation- and Terraform-specific concepts.
Backend semantics are introduced only during serialization.

### Semantic Stability

Semantic concepts should evolve significantly more slowly than provider
APIs.

### Extensibility

The model should evolve through additive changes.

## High-Level Architecture

``` text
Construct Libraries
        │
        ▼
Infrastructure Intermediate Representation
        │
 ┌──────┼───────────┐
 ▼      ▼           ▼
CloudFormation Terraform Future Backends
```

## Core Concepts

The IIR models Resources, Expressions, References, Dependencies, Assets,
Outputs, Parameters, Metadata, Lifecycle information, and Capabilities.

## Ownership

The IIR is initially owned by CDKTN to allow rapid iteration. After
validation by multiple construct ecosystems it may be extracted or
proposed for broader adoption.

## Relationship to Other RFCs

-   **RFC-04 Provider Feature Availability**: Provider capabilities are
    consumed by the IIR but remain independent.
-   **AWS Compatibility RFC-006**: Describes one consumer of the IIR.
-   **RFC-07 Azure Integration**: Provides the first independent
    validation of the IIR.

## Benefits

The IIR separates semantics from serialization, enables runtime reuse
across ecosystems, improves testing, and creates a foundation for future
backend innovation.

## Migration Strategy

The IIR will be introduced incrementally, initially mapping existing
runtime abstractions while preserving behavior. Backend serializers will
progressively consume the IIR without requiring construct changes.

## Alternatives Considered

Continuing with backend-specific synthesis increases coupling and
duplication. Exposing backend concepts to construct libraries leaks
infrastructure engine concerns into programming models. The IIR avoids
both issues.

## Success Criteria

Success is measured by multiple construct ecosystems targeting the IIR,
backend serializers remaining independent of construct implementations,
and provider-specific logic remaining outside the core runtime.

## Future Work

Future work might includes formal schemas, semantic validation, visualization
tooling, testing infrastructure, and possible ecosystem standardization
once validated.
