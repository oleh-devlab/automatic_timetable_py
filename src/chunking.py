import math

def calculate_chunks(duration, min_chunk_duration, max_chunk_duration):
    """
    Calculates the maximum number of chunks for the task.

    Args:
        duration: the total duration of the task (min).
        min_chunk_duration: the minimum chunk size (min). Determines the maximum number of chunks.
        max_chunk_duration: the maximum chunk size (min).

    Returns:
        int: the maximum number of chunks.
    """
    if min_chunk_duration is None or max_chunk_duration is None:
        return 1

    if duration <= min_chunk_duration:
        return 1

    return math.ceil(duration / min_chunk_duration)
