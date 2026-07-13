# RFC-07: Azure Construct Library Integration

**Status:** Proposal

## Summary

This RFC proposes the formal integration of the Azure Terraform
Construct Library as a first-class construct ecosystem built upon CDKTN.

Rather than treating Azure as simply another provider, this proposal
recognizes it as an independently developed construct library that
exercises the same runtime abstractions as the AWS compatibility work.
The objective is to validate that CDKTN is a cloud-neutral runtime
capable of supporting multiple construct ecosystems while avoiding
duplication of infrastructure runtime logic.

## Motivation

CDKTN was initially developed to enable Terraform synthesis while
preserving the AWS CDK programming experience. As the runtime matured,
many of its abstractions---including expressions, references, dependency
graphs, provider metadata, lifecycle modeling, synthesis, and
serialization---proved to be independent of AWS-specific concepts.

The Azure Terraform Construct Library demonstrates this in practice by
depending on CDKTN for runtime capabilities while focusing exclusively
on Azure-specific APIs and developer experience.

Supporting Azure therefore represents an architectural milestone rather
than simply adding another cloud provider. It validates that CDKTN
models infrastructure semantics instead of AWS semantics.

## Background

The Azure team has developed high-level Terraform constructs that
provide an Azure-native programming model comparable in spirit to AWS
CDK L2 constructs.

Rather than implementing its own infrastructure runtime, the Azure
library builds upon CDKTN. This creates an opportunity to evolve CDKTN
as a shared runtime while allowing each construct ecosystem to remain
responsible for its own APIs, documentation, validation, and
cloud-specific best practices.

## Goals

This RFC aims to:

-   Officially recognize the Azure Construct Library as a supported
    CDKTN consumer.
-   Validate CDKTN abstractions through an independently developed
    construct ecosystem.
-   Share runtime functionality across AWS and Azure.
-   Keep cloud-specific modeling outside CDKTN core.
-   Encourage collaboration on cloud-neutral runtime capabilities.
-   Drive the evolution of common abstractions such as the
    Infrastructure Intermediate Representation (IIR).

## Non-Goals

This RFC does not propose:

-   Azure Resource Manager compatibility.
-   CloudFormation compatibility for Azure.
-   Azure-specific implementations inside CDKTN core.
-   Forking or replacing the Azure Construct Library.
-   Introducing Azure concepts into cloud-neutral runtime abstractions.

## Architectural Principles

### Separation of Responsibilities

Construct libraries should own cloud-specific developer experience,
resource modeling, validation, and documentation.

CDKTN should own infrastructure runtime concerns including synthesis,
expressions, dependency graphs, provider abstractions, metadata,
serialization, and backend integration.

### Cloud-Neutral Runtime

Whenever Azure identifies new runtime requirements, preference should be
given to introducing generalized abstractions that also benefit AWS and
future construct ecosystems.

### Shared Semantic Model

Both AWS compatibility and Azure constructs should converge on the
shared Infrastructure Intermediate Representation defined by RFC-06.
This ensures that backend implementations consume common infrastructure
semantics rather than provider-specific models.

## Architecture

``` text
Azure Construct Library
           │
           ▼
Infrastructure Intermediate Representation
           │
           ▼
        CDKTN Runtime
           │
           ▼
Terraform Backend
           │
           ▼
Terraform Providers
```

The Azure construct library remains responsible for Azure APIs while
CDKTN remains responsible for runtime mechanics.

## Responsibilities

### Azure Construct Library

Owns:

-   Azure construct APIs
-   Resource composition
-   Azure best practices
-   Validation
-   Documentation

### CDKTN

Owns:

-   Infrastructure Intermediate Representation
-   Expressions
-   References
-   Dependency graph
-   Provider abstraction
-   Serialization
-   Terraform synthesis
-   Runtime services

### Shared Ownership

Both projects collaborate on:

-   Runtime contracts
-   Integration testing
-   Evolution of the IIR
-   Cross-project architectural guidance

## Relationship to Other RFCs

### RFC-06 -- Shared Infrastructure Intermediate Representation

RFC-06 defines the cloud-neutral semantic model consumed by construct
libraries and backend implementations. Azure Integration provides the
first independent validation of those abstractions outside the AWS
ecosystem.

### RFC-04 -- Provider Feature Availability

Azure providers participate in the same provider capability model
defined by RFC-04. Feature availability remains independent from
construct APIs and runtime semantics.

### AWS Compatibility RFC-006 -- Backend-Neutral Synthesis Architecture

The AWS Compatibility RFC describes how AWS CDK may eventually consume
the shared Infrastructure Intermediate Representation through a
backend-neutral synthesis architecture. Azure Integration demonstrates
that the same semantic model is equally applicable to independently
developed construct libraries.

## Benefits

Supporting Azure strengthens CDKTN in several ways.

It validates architectural boundaries through an independent
implementation, reduces duplication of runtime functionality, encourages
cloud-neutral abstractions, and creates opportunities for collaboration
between multiple construct ecosystems.

Perhaps most importantly, it demonstrates that CDKTN is evolving into a
reusable infrastructure runtime rather than remaining tightly coupled to
AWS compatibility.

## Migration Strategy

No significant migration is required because the Azure Construct Library
already depends upon CDKTN.

Future work will focus on progressively adopting the shared
Infrastructure Intermediate Representation while maintaining backwards
compatibility for existing Azure constructs.

As new runtime capabilities are introduced, they should first be
generalized before being consumed by Azure-specific implementations.

## Risks and Mitigations

A primary risk is introducing Azure-specific abstractions into CDKTN
core. This is mitigated by requiring that new runtime capabilities
remain cloud-neutral and broadly applicable.

Another risk is divergence between AWS and Azure runtime expectations.
The shared Infrastructure Intermediate Representation provides a common
semantic contract intended to reduce such divergence.

## Success Criteria

This RFC will be considered successful when:

-   Azure construct libraries continue to require minimal CDKTN-specific
    workarounds.
-   Runtime improvements benefit both AWS and Azure.
-   Cloud-specific APIs remain outside CDKTN core.
-   The shared Infrastructure Intermediate Representation becomes the
    common contract between construct ecosystems and backend
    implementations.

## Future Work

Future work might include expanding shared testing infrastructure, validating
additional construct ecosystems, evolving the Infrastructure
Intermediate Representation, and evaluating opportunities for broader
ecosystem standardization once the architecture has matured.
