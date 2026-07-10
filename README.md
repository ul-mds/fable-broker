![GitHub Release](https://img.shields.io/github/v/release/ul-mds/fable-broker)
![Code Coverage](https://img.shields.io/badge/Coverage-94%25-green.svg)
![License](https://img.shields.io/github/license/ul-mds/fable-broker)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white)](https://conventionalcommits.org)

# FABLE Broker

The FABLE Broker enables multi-party privacy-preserving record linkage in a trusted third party setting.
It handles match sessions, accepts bit vectors from different clients, queries matching tasks for workers in the
background and provides results to these clients once matching has finished.

The broker is split into two separate services.
One service is the web API which is powered by [FastAPI](https://fastapi.tiangolo.com/) and the other one is the
background worker leveraged by [Celery](https://docs.celeryq.dev/en/stable/getting-started/introduction.html).
The web API manages the matching sessions while the background worker queries tasks for persisting and matching vectors.

To be fully operational, the broker needs the following services to be available.

- [Neo4j](https://neo4j.com/) as a graph database to store vectors as vertices and matches as edges.
- AMQP service (e.g. [RabbitMQ](https://www.rabbitmq.com/)) as a broker for communicating with workers.
- [Redis](https://redis.io/) as a result backend to store the state of tasks.
- [FABLE PPRL Service](https://github.com/ul-mds/fable-pprl-service/) which is responsible for performing the matching
tasks.

## Deployment

Download the `docker-compose.yml` and spin up all necessary containers.

```bash
curl -O https://raw.githubusercontent.com/ul-mds/fable-broker/refs/heads/main/docker-compose.yml
docker compose up -d
```

You can watch the healthiness of the containers until they report that they are healthy.

```bash
watch -n 1 docker ps
```

The API of the Broker service is reachable via `http://localhost:8080`.
See the [Configuration section](#configuration) for more details on all available options.

## Using the API

This section provides and overview of the API and how you might use it in a PPRL workflow.
Every time a PPRL execution is performed, it starts with the creation of a match session.
Clients can then submit their bit vectors to a match session and wait for results.

### Creating and managing sessions

The `/session` endpoint is for managing the lifecycle of a match session.
Create a new session by doing a `POST` request.
You need to specify the session identifier, the match configuration, and optionally a duration after which the session
should expire automatically.
Keep in mind that the highest possible duration is determined by the server and sessions need to be refreshed to stay
alive.
By default, this limit is set to one hour.

```python
from datetime import datetime
from fable_model.broker import SessionCreationRequest, SessionCreationResponse
from fable_model.match import MatchConfig
from fastapi import status
import httpx


r = httpx.post(
    "http://localhost:8080/session",
    json=SessionCreationRequest(
        session="my-session-id",
        match_config=MatchConfig(
            measures=["jaccard", "dice"],
            thresholds=[0.9],
            aggregator="avg",
        ),
        expires_in=1_800,
    ).model_dump(),
)

assert r.status_code == status.HTTP_201_CREATED

resp = SessionCreationResponse(**r.json())

print(resp.session)
print(datetime.fromtimestamp(resp.expires_at))
print(resp.token)
```

```text
my-session-id
2026-07-10 11:33:01
7beb3d4d3527b26984b867453f24c02a
```

> [!WARNING]
> Treat the session identifier as a secret that you can only share with session participants you trust.
> It shouldn't be predictable.
> Anyone in possession of the session identifier can submit vectors to the session, affecting the quality of results.
> They can also choose to delete the session preemptively.

The session token is necessary to perform refresh and cancellation operations on a session.
Only the client that issued the session creation request should be in possession of this token.
It will only be sent once and cannot be requested again.

In the example above, the session is limited to 30 minutes.
After that, there is no guarantee that clients will be able to submit any more bit vectors.
To extend the lifetime of the session, it needs to be refreshed.
This is done by performing a `PATCH` request to the same endpoint.

```python
from datetime import datetime
from fable_model.broker import SessionUpdateRequest, SessionUpdateResponse
from fastapi import status
import httpx


r = httpx.patch(
    "http://localhost:8080/session",
    json=SessionUpdateRequest(
        session="my-session-id",
        token="7beb3d4d3527b26984b867453f24c02a",
    ).model_dump(),
)

assert r.status_code == status.HTTP_200_OK

resp = SessionUpdateResponse(**r.json())

print(resp.session)
print(datetime.fromtimestamp(resp.expires_at))
```

```text
my-session-id
2026-07-10 12:03:01
```

This session will now expire after whatever is specified in `REFRESH_SESSION_INTERVAL`.
By default, this duration is set to one hour.

If you wish to stop the session before it expires, use a `DELETE` request to the session endpoint.
This will immediately prevent clients from submitting any more bit vectors and cancel all match operations.
Match results will be purged as soon as possible.

```python
from fable_model.broker import SessionDeletionRequest
from fastapi import status
import httpx


r = httpx.request(
    "DELETE",
    "http://localhost:8080/session",
    json=SessionDeletionRequest(
        session="my-session-id",
        token="7beb3d4d3527b26984b867453f24c02a",
    ).model_dump(),
)

assert r.status_code == status.HTTP_202_ACCEPTED
```

### Submitting vectors and receiving results

There are two endpoints that can be used by clients.
One is for submitting bit vectors and one is for requesting results.
To submit bit vectors, issue a `POST` request to the `/session/submit` endpoint.

```python
from fable_model.broker import ClientSubmissionRequest, MetaBitVectorEntity, BitVectorMetadata
from fastapi import status
import httpx


r = httpx.post(
    "http://localhost:8080/session/submit",
    json=ClientSubmissionRequest(
        session="my-session-id",
        client="my-client-id",
        vectors=[
            MetaBitVectorEntity(
                id="001",
                value="CE9stxXqVmVQkHiZAZfE9w==",
                metadata=[
                    BitVectorMetadata(
                        name="count",
                        value="10",
                    ),
                ],
            ),
        ],
    ).model_dump(),
)

assert r.status_code == status.HTTP_202_ACCEPTED
```

> [!WARNING]
> Just like the session identifier, treat the client identifier like a secret.
> Anyone in possession of the client identifier can submit vectors on the client's behalf, affecting results.
> They can also obtain unauthorized access to match results of that client.

This endpoint can be called as many times as necessary.
Every time it is called, the vectors are stored at the broker and queued for matching with all other clients.
This also enables a client to submit their vectors in fixed-size chunks instead of performing one massive request.

To be able to retrieve matches, a second client needs to submit vectors first.

```python
from fable_model.broker import ClientSubmissionRequest, MetaBitVectorEntity, BitVectorMetadata
from fastapi import status
import httpx


r = httpx.post(
    "http://localhost:8080/session/submit",
    json=ClientSubmissionRequest(
        session="my-session-id",
        client="my-client-id-2",
        vectors=[
            MetaBitVectorEntity(
                id="001",
                value="DE/st1XqViVQkHiZCJfE9w==",
                metadata=[
                    BitVectorMetadata(
                        name="count",
                        value="5",
                    ),
                ],
            ),
        ],
    ).model_dump(),
)

assert r.status_code == status.HTTP_202_ACCEPTED
```

Once matching has concluded, clients can retrieve matches for the vectors they submitted by running a `POST` request
against the `/session/result` endpoint.

```python
from fable_model.broker import ClientResultRequest, ClientResultResponse
from fastapi import status
import httpx

r = httpx.post(
    "http://localhost:8080/session/result",
    json=ClientResultRequest(
        session="my-session-id",
        client="my-client-id",
        show_unfinished_results=False,
    ).model_dump(),
)

assert r.status_code == status.HTTP_200_OK

resp = ClientResultResponse(**r.json())

print(resp.finished)
print(len(resp.matches))

match = resp.matches[0]

print(match.vector.id)
print(match.similarities)
print(match.aggregated_similarity)
print(match.reference_metadata)
```

```text
True
1
001
[0.90625, 0.9508196721311475]
0.9285348360655737
[BitVectorMetadata(name='count', value='5')]
```

The result contains a list of matched vectors which have been found to be sufficiently similar to vectors submitted by
other clients.
Every vector in the list contains the computed similarities, the aggregated similarity, as well as the metadata of the
other client's vector.
This information can be used to perform automated decision-making.

If you are not sure whether matching has concluded or not, you can run the same request as above.
The `finished` field in the response tells you whether matching has concluded or not.
If `show_unfinished_results` is set to `False` in the request and matching has not finished yet, then the result list is
empty.
However, you can set that field to `True` in order to receive preemptive results even when matching has not finished
yet.

## Configuration

The following table shows all available configuration options.
These variables can either be defined in `.env` or in the `environment` section of the containers defined inside the
`docker-compose.yml` file.

| **Environment variable** | **Description**                                                                     | **Default**                         |
|--------------------------|-------------------------------------------------------------------------------------|-------------------------------------|
| PPRL_SERVICE_BASE_URL    | Base URL for the PPRL service to be able to perform matching.                       | http://localhost:8080               |
| NEO4J_URL                | URL where Neo4j is available to persist matches.                                    | bolt://localhost:7687               |
| AMQP_URL                 | URL where the message broker is available to communicate with workers.              | amqp://guest:guest@localhost:5672// |
| REDIS_URL                | URL where Redis is available which is used as the result backend for the workers.   | redis://localhost:6379/0            |
| MAX_SESSION_TIMEOUT      | The maximum value for the lifetime of a session in seconds.                         | 3600                                |
| REFRESH_SESSION_INTERVAL | New lifetime of a session in seconds after a session gets refreshed.<sup>1)</sup>   | 3600                                |
| TASK_CLEANUP_INTERVAL    | Time in seconds that is waited until the service checks again for expired sessions. | 10                                  |
| EXPOSE_DOCS              | If set to true, all FastAPI documentation endpoints are exposed.<sup>2)</sup>       | 1                                   |

<sup>1)</sup> After a session got refreshed, this session will expire in `REFRESH_SESSION_INTERVAL` seconds.
<sup>2)</sup> The documentation endpoints are `/openapi.json`, `/docs` and `/redoc`.

## Development and running tests

Tests are implemented with [pytest](https://pypi.org/project/pytest/).
Set up tests by copying `.env.example` into a new file called `.env` and spin up all necessary containers.
Pre-existing environment variables take precedence and will not bew overwritten by the contents of `.env`.

```bash
cp .env.example .env
docker compose -f tests/docker-compose.yml up -d
```

You can then execute tests by running `pytest tests`.
Tests will automatically spin up the web API and a worker.
If you need them for development purposes, you can start the web API with `fable-broker-api` and a worker process
with `fable-broker-worker`.

## License

The FABLE Broker service is released under the MIT license.
