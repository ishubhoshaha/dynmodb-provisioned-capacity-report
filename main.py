import math
import re
import boto3
import csv
import io
import os
import datetime

from collections import namedtuple
from fastapi import FastAPI, BackgroundTasks, status

app = FastAPI()



all_gsi_info = []
ProvisionedCapacity = namedtuple("ProvisionedCapacity", "provision_read provision_write")
class ResourceInterface:
    def __init__(self):
        self.dynamodb = boto3.client('dynamodb')
        self.cloudwatch = boto3.client('cloudwatch')

    def save_gsi_info(self, table_name, gsi_info):
        # process and save  gsi info with proviosned value
        try:
            data = {
                "name": gsi_info["IndexName"],
                "table_name": table_name,
                "provsioned_read": gsi_info["ProvisionedThroughput"]["ReadCapacityUnits"],
                "provsioned_write": gsi_info["ProvisionedThroughput"]["WriteCapacityUnits"]
            }
            all_gsi_info.append(data)
            return True
        except Exception as E:
            print(E)
            return False

    def get_all_tables_name(self):
        '''
        list out all existing dynamodb table
        :return: all_tables_name - list of names
        '''
        all_tables_name = []
        LastEvaluatedTableName = ""
        while LastEvaluatedTableName != None:
            if LastEvaluatedTableName == "":
                tables = self.dynamodb.list_tables()
                all_tables_name.extend(tables["TableNames"])
                LastEvaluatedTableName = tables.get("LastEvaluatedTableName", None)
            else:
                tables = self.dynamodb.list_tables(ExclusiveStartTableName=LastEvaluatedTableName)
                all_tables_name.extend(tables["TableNames"])
                LastEvaluatedTableName = tables.get("LastEvaluatedTableName", None)

        return all_tables_name

    def filter_capp_tables(self):
        '''
        filter only customer app table
        :return:
        capp_tables_name - filtered list of table names
        '''
        all_tables_name = self.get_all_tables_name()
        # all_tables_name = demo_response
        capp_tables_name = []
        table_prefix = os.environ['TABLE_PREFIX']
        for table in all_tables_name:
            if re.match(r'^{}'.format(table_prefix), table):
                capp_tables_name.append(table)

        return capp_tables_name

    def get_cloudwatch_metric_data(self, period, table_name, metric_name):
        '''
        utility  function for grabbing metric data
        :param period:
        :param table_name:
        :param metric_name: either ConsumedReadCapacityUnits/ConsumedWriteCapacityUnits
        :return:  dictionary data
        '''
        current_time = datetime.datetime.now()
        metric_data = self.cloudwatch.get_metric_data(
            MetricDataQueries=[
                {
                    'Id': "_".join(table_name.split('-')),
                    'MetricStat': {
                        'Metric': {
                            'Namespace': "AWS/DynamoDB",
                            'MetricName': metric_name,
                            'Dimensions': [
                                {
                                    'Name': 'TableName',
                                    'Value': table_name
                                },
                            ],
                        },
                        'Stat': 'Sum',
                        'Period': period,
                    },
                }
            ],
            StartTime=current_time - datetime.timedelta(days=14),
            EndTime=current_time,
        )
        return metric_data

    def get_provisioned_capacity(self, table_name):

        table_info = self.dynamodb.describe_table(TableName = table_name)
        proviosned_read = table_info["Table"]["ProvisionedThroughput"]["ReadCapacityUnits"]
        proviosned_write = table_info["Table"]["ProvisionedThroughput"]["WriteCapacityUnits"]

        #incase the table has gsi then enlist them for calculation
        gsi_infos = table_info["Table"].get("GlobalSecondaryIndexes")
        if gsi_infos and len(gsi_infos)>0:
            for gsi_info in gsi_infos:
                self.save_gsi_info(table_name, gsi_info)

        return ProvisionedCapacity(proviosned_read, proviosned_write)

    def get_consumed_capacity(self, table_name):
        '''
        :param table_name: dynamodb table name
        :return:
        max_pick - maximum pick of consumed capacity of last 2 week
        average_consumed_capacity
        '''
        ConsumedCapacity = namedtuple("ConsumedCapacity", "consumed_read consumed_write")

        period = 1 * 60
        read_metric_data = self.get_cloudwatch_metric_data(period, table_name, "ConsumedReadCapacityUnits")
        write_metric_data =  self.get_cloudwatch_metric_data(period, table_name, "ConsumedWriteCapacityUnits")
        if len(read_metric_data["MetricDataResults"]) > 0 and len(write_metric_data["MetricDataResults"]) > 0:
            sort_consumed_capacity_value = sorted(read_metric_data["MetricDataResults"][0]["Values"])
            average_consumed_read_capacity = (sum(sort_consumed_capacity_value[-10:])/10)/period

            sort_consumed_capacity_value = sorted(write_metric_data["MetricDataResults"][0]["Values"])
            average_consumed_write_capacity = (sum(sort_consumed_capacity_value[-10:]) / 10) / period
            return_val = ConsumedCapacity(average_consumed_read_capacity, average_consumed_write_capacity)
            return return_val

        # // return 0 since no values are registered in aws metrics for "table_name" dynamodb table
        return ConsumedCapacity(0, 0)


    @staticmethod
    def get_recommend_value(tables_info):
        RecommendValue = namedtuple("RecommendValue", "recommend_read recommend_write")
        recommend_read = math.ceil(tables_info["provisioned_capacity"].provision_read*1.3)
        recommend_write = math.ceil(tables_info["provisioned_capacity"].provision_read*1.3)
        return RecommendValue(recommend_read, recommend_write)

def make_report(tables_info):
    csvio = io.StringIO()
    writer = csv.writer(csvio)
    writer.writerow(["TableName", "Provisioned Read", "Provisioned Write", "Consumed Read", "Consumed Write", "Recommend Read", "Recommend Write"])
    for table in tables_info:
        recommend_value = ResourceInterface.get_recommend_value(table)
        writer.writerow([table["name"], table["provisioned_capacity"].provision_read, table["provisioned_capacity"].provision_write, table["consumed_capacity"].consumed_read, table["consumed_capacity"].consumed_read, recommend_value.recommend_read, recommend_value.recommend_write])
    s3 = boto3.client('s3')
    bucket_name = os.environ.get("BUCKET_NAME")
    s3.put_object(Body=csvio.getvalue(), ContentType='text/csv', Bucket=bucket_name, Key="dynamodb_capacity_report_{}.csv".format(datetime.datetime.now().strftime("%d_%m_%Y")))
    csvio.close()

def main():
    aws = ResourceInterface()
    capp_tables = aws.filter_capp_tables()
    tables_info = []
    for table in capp_tables:
        start = datetime.datetime.now()
        data = {
            "name": table,
            "provisioned_capacity": aws.get_provisioned_capacity(table),
            "consumed_capacity": aws.get_consumed_capacity(table)
        }
        tables_info.append(data)
        end = datetime.datetime.now()
        print(end-start)

    for gsi in  all_gsi_info:
        data = {
            "name": "gsi"+ ":" +gsi.get("table_name") + ":" + gsi.get("name"),
            "provisioned_capacity": ProvisionedCapacity(gsi.get('provsioned_read'), gsi.get('provsioned_write')),
            "consumed_capacity": aws.get_consumed_capacity(gsi.get("name"))
        }
        tables_info.append(data)
    make_report(tables_info)

@app.get("/make-capacity-report/{pattarn}/{bucket_name}")
async def make_capacity_report(pattarn, bucket_name, background_tasks: BackgroundTasks):
    os.environ['TABLE_PREFIX'] = pattarn
    os.environ["BUCKET_NAME"] = bucket_name
    background_tasks.add_task(main)
    return {"status": "200"}


@app.get("/status")
async def root():
    return {"status": "OK"}