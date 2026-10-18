snowsql -q "select 1"
snowsql -c dev -f daily.sql -D day=1
snowsql --username alice --accountname example-account --warehouse wh -q "select 1"
