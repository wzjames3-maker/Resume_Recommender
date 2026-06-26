from src.common.logger import get_logger
from src.resume_parser.segmenter import get_segmenter
from src.resume_parser.chunk_builder import get_chunk_builder
from src.vector_index.vector_writer import get_vector_writer

logger = get_logger('indexing')


def index_resume(resume_id: str, raw_text: str) -> int:
    '''Index a resume: segment -> chunk -> write vectors. Returns chunk count.'''
    segmenter = get_segmenter()
    segmentation = segmenter.segment(raw_text)

    chunk_builder = get_chunk_builder()
    chunk_result = chunk_builder.build(
        segments=segmentation.segments,
        resume_id=resume_id,
        full_text=raw_text,
    )

    writer = get_vector_writer()
    writer.write_chunks(chunk_result.chunks, resume_id)
    logger.info(f'Index OK: resume_id={resume_id}, chunks={len(chunk_result.chunks)}')
    return len(chunk_result.chunks)
