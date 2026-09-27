import os
import uvicorn
from pfai.logging_setup import setup_logging

log = setup_logging('pfai.web')

if __name__ == '__main__':
    host = os.getenv('PFAI_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('PFAI_PORT', '8000')))
    log.info('starting PFAI web host=%s port=%s', host, port)
    uvicorn.run(
        'pfai.api:app',
        host=host,
        port=port,
        reload=False,
    )
