from neo4j import Driver, GraphDatabase, Transaction

from fable_model.broker import BitVectorMetadata, MetaBitVectorEntity, MatchedClientVector
from fable_model.common import BitVectorEntity
from fable_model.match import Match


def connect_neo4j(url: str) -> Driver:
    """
    Creates a new connection to the Neo4j database at the specified URL.

    Args:
        url: database URL

    Returns:
        database driver
    """
    return GraphDatabase.driver(url)


def delete_all(driver: Driver):
    """
    Deletes all nodes and relationships.

    Args:
        driver: database driver
    """
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")


def delete_for_session(driver: Driver, session: str):
    """
    Deletes all nodes and relationships belonging to a match session.

    Args:
        driver: database driver
        session: match session
    """
    with driver.session() as s:
        s.run(
            "MATCH (b:BitVector {session: $session}) DETACH DELETE b",
            session=session,
        )


def serialize_bit_vector_metadata(metadata_lst: list[BitVectorMetadata]) -> str:
    """
    Converts a list of metadata objects into a string of key-value pairs.

    Args:
        metadata_lst: list of metadata objects

    Returns:
        string of key-value pairs
    """
    if len(metadata_lst) == 0:
        return ""

    return ",".join([f"{m.name}={m.value}" for m in metadata_lst])


def deserialize_bit_vector_metadata(s: str) -> list[BitVectorMetadata]:
    """
    Converts a string of key-value pairs into a list of metadata objects.

    Args:
        s: string of key-value pairs

    Returns:
        list of metadata objects

    Raises:
        ValueError: if an invalid key-value pair is in the string
    """
    if s == "":
        return []

    metadata_lst: list[BitVectorMetadata] = []

    for md_pair_str in s.split(","):
        try:
            colon_idx = md_pair_str.index("=")
            metadata_lst.append(BitVectorMetadata(name=md_pair_str[0:colon_idx], value=md_pair_str[colon_idx + 1 :]))
        except ValueError:
            raise ValueError(f"Metadata string '{md_pair_str}' is not a key-value pair")

    return metadata_lst


def _create_client_vectors_tx(
    tx: Transaction,
    session: str,
    client: str,
    vector_lst: list[MetaBitVectorEntity],
) -> list[int]:
    return tx.run(
        """
        UNWIND $vectors AS vector
        CREATE (b:BitVector {
          session: $session,
          client: $client,
          id: vector.id,
          value: vector.value,
          meta: vector.meta
        })
        RETURN collect(id(b))
        """,
        session=session,
        client=client,
        vectors=[{"id": v.id, "value": v.value, "meta": serialize_bit_vector_metadata(v.metadata)} for v in vector_lst],
    ).single(True)[0]


def insert_vectors_for_client(
    driver: Driver,
    session: str,
    client: str,
    vector_lst: list[MetaBitVectorEntity],
) -> list[int]:
    """
    Inserts vectors into the database, assigning them to the specified client partaking in the specified match session.

    Args:
        driver: database driver
        session: match session
        client: client identifier
        vector_lst: list of vectors

    Returns:
        internal IDs of generated nodes
    """
    with driver.session() as s:
        id_lst = s.execute_write(
            _create_client_vectors_tx,
            session=session,
            client=client,
            vector_lst=vector_lst,
        )

    return id_lst


def _get_vectors_by_id_tx(tx: Transaction, id_lst: list[int]) -> list[BitVectorEntity]:
    result = tx.run(
        "MATCH (b:BitVector) WHERE id(b) IN $ids RETURN b.id AS id, b.value AS value",
        ids=id_lst,
    )

    return [
        BitVectorEntity(
            id=r["id"],
            value=r["value"],
        )
        for r in result
    ]


def get_vectors_by_id(driver: Driver, id_lst: list[int]) -> list[BitVectorEntity]:
    """
    Returns vectors by their internal node ID.

    Args:
        driver: database driver
        id_lst: internal node IDs

    Returns:
        list of vectors with specified node IDs
    """
    with driver.session() as s:
        vector_lst = s.execute_read(_get_vectors_by_id_tx, id_lst=id_lst)

    return vector_lst


def _get_meta_vectors_by_id_tx(tx: Transaction, id_lst: list[int]) -> list[MetaBitVectorEntity]:
    result = tx.run(
        "MATCH (b:BitVector) WHERE id(b) IN $ids RETURN b.id AS id, b.value AS value, b.meta AS meta",
        ids=id_lst,
    )

    return [
        MetaBitVectorEntity(
            id=r["id"],
            value=r["value"],
            metadata=deserialize_bit_vector_metadata(r["meta"]),
        )
        for r in result
    ]


def get_meta_vectors_by_id(driver: Driver, id_lst: list[int]) -> list[MetaBitVectorEntity]:
    """
    Returns vectors by their internal node ID.

    Args:
        driver: database driver
        id_lst: internal node IDs

    Returns:
        list of vectors with specified node IDs and annotated metadata
    """
    with driver.session() as s:
        vector_lst = s.execute_read(_get_meta_vectors_by_id_tx, id_lst=id_lst)

    return vector_lst


def _insert_matches_tx(
    tx: Transaction,
    session: str,
    domain_client: str,
    range_client: str,
    matches: list[Match],
) -> list[int]:
    # TODO: this can be improved
    # MATCH (a:BitVector) WHERE id(a) IN [domain_id, range_id]
    # WITH COLLECT(a) AS l
    # RETURN l[0], l[1]
    # With you can work with domain and range vectors (order is not preserved!).
    # This further means that the worker needs to use IDs and not with vectors.

    # Set a sentinel of -1 for the aggregated similarity in case it is None because Neo4j does not allow None values
    # for properties.
    return tx.run(
        """
        UNWIND $matches AS match
        MATCH (a:BitVector {
          session: $session,
          client: $domainClient,
          value: match.domainValue,
          id: match.domainId
        })
        WITH a, match
        MATCH (b:BitVector {
          session: $session,
          client: $rangeClient,
          value: match.rangeValue,
          id: match.rangeId
        })
        MERGE (a)-[s:IS_SIMILAR_TO {
          similarities: match.similarities,
          aggregatedSimilarity: match.aggregatedSimilarity
        }]->(b)
        RETURN collect(id(s))
        """,
        session=session,
        domainClient=domain_client,
        rangeClient=range_client,
        matches=[
            {
                "domainId": m.domain.id,
                "domainValue": m.domain.value,
                "rangeId": m.range.id,
                "rangeValue": m.range.value,
                "similarities": m.similarities,
                "aggregatedSimilarity": m.aggregated_similarity if m.aggregated_similarity is not None else -1,
            }
            for m in matches
        ],
    ).single(True)[0]


def insert_matches(
    driver: Driver,
    session: str,
    domain_client: str,
    range_client: str,
    matches: list[Match],
) -> list[int]:
    """
    Inserts matches into the database by creating relationships between the respective nodes.

    Args:
        driver: database driver
        session: match session
        domain_client: domain client identifier
        range_client: range client identifier
        matches: list of matches

    Returns:
        number of generated relationships
    """
    if len(matches) == 0:
        return []

    with driver.session() as s:
        rel_ids = s.execute_write(
            _insert_matches_tx,
            session=session,
            domain_client=domain_client,
            range_client=range_client,
            matches=matches,
        )

    return rel_ids


def _get_vector_ids_for_client_tx(tx: Transaction, session: str, client: str) -> list[int]:
    return tx.run(
        "MATCH (b:BitVector { session: $session, client: $client }) RETURN collect(id(b))",
        session=session,
        client=client,
    ).single(True)[0]


def get_vector_ids_for_client(driver: Driver, session: str, client: str) -> list[int]:
    """
    Returns the internal node IDs for the vectors stored for a particular client.

    Args:
        driver: database driver
        session: match session
        client: client identifier

    Returns:
        list of internal node IDs
    """
    with driver.session() as s:
        vec_ids = s.execute_read(_get_vector_ids_for_client_tx, session=session, client=client)

    return vec_ids


def _get_matches_for_client_tx(tx: Transaction, session: str, client: str) -> list[MatchedClientVector]:
    result = tx.run(
        """
        MATCH (a:BitVector {session: $session, client: $client })
        -[s:IS_SIMILAR_TO]-
        (b:BitVector { session: $session })
        WHERE b.client <> $client
        RETURN a, b, s
        """,
        session=session,
        client=client,
    )

    # Since the aggregated similarity can be None and Neo4j does not allow properties to be null, -1 is used as a
    # sentinel.
    def _check_for_sentinel(value: float) -> float | None:
        if value == -1:
            return None
        return value

    return [
        MatchedClientVector(
            vector=MetaBitVectorEntity(
                id=r["a"]["id"], value=r["a"]["value"], metadata=deserialize_bit_vector_metadata(r["a"]["meta"])
            ),
            similarities=r["s"]["similarities"],
            aggregated_similarity=_check_for_sentinel(r["s"]["aggregatedSimilarity"]),
            reference_metadata=deserialize_bit_vector_metadata(r["b"]["meta"]),
        )
        for r in result
    ]


def get_matches_for_client(driver: Driver, session: str, client: str) -> list[MatchedClientVector]:
    """
    Returns the list of identified matches for a particular client.

    Args:
        driver: database driver
        session: match session
        client: client identifier

    Returns:
        list of matches
    """
    with driver.session() as s:
        matches = s.execute_read(_get_matches_for_client_tx, session=session, client=client)

    return matches
