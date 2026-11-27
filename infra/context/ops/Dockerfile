FROM postgres:17

# Scripts travel with the image; Coolify need not retain the Git checkout at runtime.
COPY --chmod=0555 backup.sh restore.sh schedule.sh /ops/
RUN sed -i 's/\r$//' /ops/*.sh \
    && chmod 0555 /ops/*.sh \
    && for script in /ops/*.sh; do bash -n "$script"; done
