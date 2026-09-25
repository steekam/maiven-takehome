let results = [];
let calls = [];

export function configureDatabaseResults(...nextResults) {
  results = [...nextResults];
  calls = [];
}

export function getDatabaseCalls() {
  return calls;
}

export function getDatabase() {
  return {
    select(selection) {
      const call = { selection };
      calls.push(call);
      const result = results.shift() ?? [];
      const builder = {
        from(table) {
          call.table = table;
          return builder;
        },
        where(condition) {
          call.condition = condition;
          return builder;
        },
        orderBy(...order) {
          call.order = order;
          return builder;
        },
        limit(limit) {
          call.limit = limit;
          return Promise.resolve(result);
        },
      };
      return builder;
    },
  };
}
