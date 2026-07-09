from fable_model.broker import BitVectorMetadata, MatchedClientVector
from fable_model.match import Match
from neo4j import Driver, Transaction, Record
import pytest
from random import Random

from fable_broker.internal.graph import (
    serialize_bit_vector_metadata,
    deserialize_bit_vector_metadata,
    delete_all,
    delete_for_session,
    insert_vectors_for_client,
    get_vectors_by_id,
    get_meta_vectors_by_id,
    insert_matches,
    get_vector_ids_for_client,
    get_matches_for_client,
)
from tests.helpers import random_meta_vec, random_vec


@pytest.mark.parametrize(
    "bit_vector_metadata_list,expected",
    [
        ([], ""),
        ([BitVectorMetadata(name="foo", value="bar")], "foo=bar"),
        ([BitVectorMetadata(name="foo", value="bar"), BitVectorMetadata(name="oof", value="rab")], "foo=bar,oof=rab"),
    ],
)
def test_serialize_bit_vector_metadata(bit_vector_metadata_list, expected):
    assert serialize_bit_vector_metadata(bit_vector_metadata_list) == expected


@pytest.mark.parametrize(
    "serialized_data,expected",
    [
        ("", []),
        ("foo=bar", [BitVectorMetadata(name="foo", value="bar")]),
        ("foo=bar,oof=rab", [BitVectorMetadata(name="foo", value="bar"), BitVectorMetadata(name="oof", value="rab")]),
    ],
)
def test_deserialize_bit_vector_metadata(serialized_data, expected):
    assert deserialize_bit_vector_metadata(serialized_data) == expected


def test_deserialize_bit_vector_metadata_error():
    with pytest.raises(ValueError) as e:
        deserialize_bit_vector_metadata("test")

    assert str(e.value) == "Metadata string 'test' is not a key-value pair"


def test_delete_all(graphdb_driver: Driver):
    def create_test_nodes_tx(tx: Transaction) -> Record:
        result = tx.run(
            """
            CREATE (a:BitVector {foo: 1})
            -[l:LIKES]->
            (b:BitVector {foo: 2})
            RETURN id(a), id(l), id(b)
            """
        )
        return result.single(True)

    def count_test_nodes_tx(tx: Transaction) -> int:
        result = tx.run("MATCH (n:BitVector) RETURN COUNT(n)")
        return result.single(True)[0]

    with graphdb_driver.session() as s:
        assert s.execute_write(create_test_nodes_tx) is not None

    delete_all(graphdb_driver)

    with graphdb_driver.session() as s:
        r = s.execute_read(count_test_nodes_tx)
        assert r == 0


def test_delete_for_session(graphdb_driver: Driver):
    def create_test_vector_node_tx(tx: Transaction, session: str) -> Record:
        return tx.run(
            "CREATE (b:BitVector {session: $session}) RETURN id(b)",
            session=session,
        ).single(True)

    def count_session_vector_tx(tx: Transaction, session: str) -> int:
        return tx.run(
            "MATCH (b:BitVector {session: $session}) RETURN COUNT(b)",
            session=session,
        ).single(True)[0]

    with graphdb_driver.session() as s:
        assert s.execute_write(create_test_vector_node_tx, session="foo") is not None
        assert s.execute_write(create_test_vector_node_tx, session="bar") is not None

    delete_for_session(graphdb_driver, "foo")

    with graphdb_driver.session() as s:
        assert s.execute_read(count_session_vector_tx, session="foo") == 0
        assert s.execute_read(count_session_vector_tx, session="bar") == 1


def test_insert_vector_for_client(graphdb_driver: Driver, rng: Random):
    def count_client_vector_tx(tx: Transaction, session: str, client: str) -> int:
        return tx.run(
            "MATCH (b:BitVector { session: $session, client: $client }) RETURN COUNT(b)",
            session=session,
            client=client,
        ).single(True)[0]

    vec_count = 100

    assert (
        len(
            insert_vectors_for_client(
                graphdb_driver,
                "foosession",
                "fooclient",
                [random_meta_vec(rng) for _ in range(0, vec_count)],
            )
        )
        == vec_count
    )

    with graphdb_driver.session() as s:
        assert s.execute_read(count_client_vector_tx, session="foosession", client="fooclient") == vec_count


def test_get_vectors_by_id(graphdb_driver: Driver, rng: Random):
    b1, b2 = random_vec(rng), random_vec(rng)

    with graphdb_driver.session() as s:
        id_0 = s.execute_write(
            lambda tx: tx.run(f'CREATE (b:BitVector {{id: "{b1.id}", value: "{b1.value}"}}) RETURN id(b)').single(True)[
                0
            ]
        )

        id_1 = s.execute_write(
            lambda tx: tx.run(f'CREATE (b:BitVector {{id: "{b2.id}", value: "{b2.value}"}}) RETURN id(b)').single(True)[
                0
            ]
        )

    vectors = get_vectors_by_id(graphdb_driver, [id_0, id_1])

    assert b1 in vectors
    assert b2 in vectors


def test_get_meta_vectors_by_id(graphdb_driver: Driver, rng: Random):
    b1, b2 = random_meta_vec(rng), random_meta_vec(rng)

    with graphdb_driver.session() as s:
        id_0 = s.execute_write(
            lambda tx: tx.run(
                f'''
                CREATE (b:BitVector {{
                  id: "{b1.id}",
                  value: "{b1.value}",
                  meta: "{serialize_bit_vector_metadata(b1.metadata)}"
                }})
                RETURN id(b)
                '''
            ).single(True)[0]
        )

        id_1 = s.execute_write(
            lambda tx: tx.run(
                f'''
                CREATE (b:BitVector {{
                  id: "{b2.id}",
                  value: "{b2.value}",
                  meta: "{serialize_bit_vector_metadata(b2.metadata)}"
                }})
                RETURN id(b)
                '''
            ).single(True)[0]
        )

    vectors = get_meta_vectors_by_id(graphdb_driver, [id_0, id_1])

    assert b1 in vectors
    assert b2 in vectors


@pytest.mark.parametrize(
    "similarities,aggregated_similarity",
    [
        ([0.8], None),
        ([0.2, 0.55, 0.94], None),
        ([0.8], 0.8),
        ([0.2, 0.55, 0.94], 0.56),
    ],
)
def test_insert_matches(
    graphdb_driver: Driver,
    rng: Random,
    similarities: list[float],
    aggregated_similarity: float | None,
):
    b1, b2 = random_vec(rng), random_vec(rng)

    with graphdb_driver.session() as s:
        id_0: int = s.execute_write(
            lambda tx: tx.run(
                f'''
                CREATE (b:BitVector {{
                  session: "session",
                  client: "client1",
                  id: "{b1.id}",
                  value: "{b1.value}",
                  meta: "foo=bar"
                }})
                RETURN id(b)
                '''
            ).single(True)[0]
        )

        id_1: int = s.execute_write(
            lambda tx: tx.run(
                f'''
                CREATE (b:BitVector {{
                  session: "session",
                  client: "client2",
                  id: "{b2.id}",
                  value: "{b2.value}",
                  meta: "foo=baz"
                }})
                RETURN id(b)
                '''
            ).single(True)[0]
        )

    rel_ids = insert_matches(
        graphdb_driver,
        session="session",
        domain_client="client1",
        range_client="client2",
        matches=[Match(domain=b1, range=b2, similarities=similarities, aggregated_similarity=aggregated_similarity)],
    )

    assert len(rel_ids) == 1

    with graphdb_driver.session() as s:
        r = s.execute_read(
            lambda tx: tx.run(
                f'''
                MATCH (a:BitVector {{ id: "{b1.id}" }})
                -[s:IS_SIMILAR_TO]->
                (b:BitVector {{ id: "{b2.id}" }})
                RETURN id(a), id(b), s.similarities, s.aggregatedSimilarity
                '''
            ).single(True)
        )

        assert r[0] == id_0
        assert r[1] == id_1
        assert r[2] == similarities
        # -1 is stored as a sentinel for None because Neo4j does not allow null properties.
        assert r[3] == aggregated_similarity if aggregated_similarity is not None else -1


def test_insert_empty_matches(graphdb_driver):
    rel_ids = insert_matches(
        graphdb_driver,
        session="session",
        domain_client="client1",
        range_client="client2",
        matches=[],
    )

    assert rel_ids == []


def test_get_vector_ids_for_client(graphdb_driver: Driver):
    with graphdb_driver.session() as s:
        id_0: int = s.execute_write(
            lambda tx: tx.run('CREATE (b:BitVector {session: "session", client: "client"}) RETURN id(b)').single(True)[
                0
            ]
        )

    vec_ids = get_vector_ids_for_client(graphdb_driver, "session", "client")

    assert vec_ids == [id_0]


@pytest.mark.parametrize(
    "similarities,aggregated_similarity",
    [
        ([0.8], None),
        ([0.2, 0.55, 0.94], None),
        ([0.8], 0.8),
        ([0.2, 0.55, 0.94], 0.56),
    ],
)
def test_get_matches_for_client(
    graphdb_driver: Driver,
    rng: Random,
    similarities: list[float],
    aggregated_similarity: float | None,
):
    b1, b2 = random_meta_vec(rng), random_meta_vec(rng)

    with graphdb_driver.session() as s:
        s.execute_write(
            lambda tx: tx.run(
                f'''
                CREATE (:BitVector {{
                  session: "session",
                  client: "client1",
                  id: "{b1.id}",
                  value: "{b1.value}",
                  meta: "{serialize_bit_vector_metadata(b1.metadata)}"
                }})
                -[:IS_SIMILAR_TO {{
                  similarities: {similarities},
                  aggregatedSimilarity: {aggregated_similarity if aggregated_similarity is not None else -1}
                }}]->
                (:BitVector {{
                  session: "session",
                  client: "client2",
                  id: "{b2.id}",
                  value: "{b2.value}",
                  meta: "{serialize_bit_vector_metadata(b2.metadata)}"
                }})
                '''
            )
        )

    assert get_matches_for_client(graphdb_driver, "session", "client1") == [
        MatchedClientVector(
            vector=b1,
            similarities=similarities,
            aggregated_similarity=aggregated_similarity,
            reference_metadata=b2.metadata,
        ),
    ]

    assert get_matches_for_client(graphdb_driver, "session", "client2") == [
        MatchedClientVector(
            vector=b2,
            similarities=similarities,
            aggregated_similarity=aggregated_similarity,
            reference_metadata=b1.metadata,
        ),
    ]
