snowsql --password PlantedInventorySecretValue789 -q "select 1"
snowsql -o exit_on_error=false -f job.sql
