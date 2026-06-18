import _ from "lodash";

export function groupSum(items, groupKey, valueKey) {
  const grouped = _.groupBy(items, groupKey);
  return _.mapValues(grouped, (rows) => _.sumBy(rows, valueKey));
}
