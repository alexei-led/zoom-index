import boto3
import json
import logging
import os
import requests

from gremlin_python.structure.graph import Graph
from gremlin_python.process.traversal import T, P, Operator
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

s3 = boto3.client('s3')


def setup_graph():
    try:
        graph = Graph()
        connstring = os.environ.get('GRAPH_DB')
        logging.info('trying to login')
        g = graph.traversal().withRemote(DriverRemoteConnection(connstring, 'g'))
        logging.info('successfully logged in')
    except Exception as e:  # Shouldn't really be so broad
        logging.error(e, exc_info=True)
        raise Exception('could not connect to Neptune, error: ' + str(e))
    return g


def get_resource(resource_id, g):
    resource = g.V(resource_id).toList()
    logging.info("resources found are: %s" % resource)
    # if not found
    if not resource:
        return None
    # just in case there is more than one - shouldn't happen
    if len(resource) > 1:
        raise ValueError('more than one resource found for id: %s' % resource_id)
    return resource[-1]


def new_resource(resource_id, resource_type, name=None, region=None, zone=None, tags=None, relationships=None):
    logging.info('adding a new resource')
    g = setup_graph()
    try:
        logging.info('adding a new resource to graph')
        resource = get_resource(resource_id=resource_id, g=g)
        if not resource:  # insert new vertex if not exists
            logging.info('adding new vertex with %s id', resource_id)
            resource = g.addV('resource').property(T.id, resource_id).next()
        # add type
        g.V(resource).property('type', resource_type).next()
        # add name
        if name:
            g.V(resource).property('name', name).next()
        # add region
        if region:
            g.V(resource).property('region', region).next()
        # add availability zone
        if region:
            g.V(resource).property('zone', zone).next()
        # add tags
        if tags:
            logging.info("received tags: " + str(tags))
            for tag_name, tag_value in tags.items():
                g.V(resource).property(tag_name, tag_value).next()
        # add relationships
        if relationships:
            logging.info("received relationships: " + str(relationships))
            for to_resource_id, to_resource_type, relationship_name in relationships.items():
                # try to find "to" resource, insert if not found
                to_resource = get_resource(to_resource_id, g)
                if not to_resource:
                    new_resource(to_resource_id, to_resource_type)
                logging.info('adding new edge from %s to %s', resource_id, to_resource_id)
                g.V(resource).addE(relationship_name).to(to_resource_id).next()
    except(ValueError, AttributeError, TypeError) as e:
        logging.error(e, exc_info=True)
        raise Exception('could not insert resource, error: ' + str(e))
    logging.info("successfully inserted new resource")
    return {"id": resource_id}


def lambda_handler(event, context):
    """
    Parameters
    ----------
    event: dict, required
        Amazon S3 Put Sample Event Format

        {
            "Records": [{
                "eventVersion": "2.0",
                "eventTime": "1970-01-01T00:00:00.000Z",
                "requestParameters": {
                    "sourceIPAddress": "127.0.0.1"
                },
                "s3": {
                    "configurationId": "testConfigRule",
                    "object": {
                        "eTag": "0123456789abcdef0123456789abcdef",
                        "sequencer": "0A1B2C3D4E5F678901",
                        "key": "HappyFace.jpg",
                        "size": 1024
                    },
                    "bucket": {
                        "arn": ${{bucketarn}},
                        "name": "sourcebucket",
                        "ownerIdentity": {
                            "principalId": "EXAMPLE"
                        }
                    },
                    "s3SchemaVersion": "1.0"
                },
                "responseElements": {
                    "x-amz-id-2": "EXAMPLE123/5678abcdefghijklambdaisawesome/mnopqrstuvwxyzABCDEFGH",
                    "x-amz-request-id": "EXAMPLE123456789"
                },
                "awsRegion": "us-east-1",
                "eventName": "ObjectCreated:Put",
                "userIdentity": {
                    "principalId": "EXAMPLE"
                },
                "eventSource": "aws:s3"
            }]
        }

        https://docs.aws.amazon.com/lambda/latest/dg/eventsources.html#eventsources-s3-put

    context: object, required
        Lambda Context runtime methods and attributes

    Attributes
    ----------

    context.aws_request_id: str
         Lambda request ID
    context.client_context: object
         Additional context when invoked through AWS Mobile SDK
    context.function_name: str
         Lambda function name
    context.function_version: str
         Function version identifier
    context.get_remaining_time_in_millis: function
         Time in milliseconds before function times out
    context.identity:
         Cognito identity provider context when invoked through AWS Mobile SDK
    context.invoked_function_arn: str
         Function ARN
    context.log_group_name: str
         Cloudwatch Log group name
    context.log_stream_name: str
         Cloudwatch Log stream name
    context.memory_limit_in_mb: int
        Function memory

        https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    ------
    dict {
        "id": ${{resource_id}}
    }
    """

    try:
        # retrieve bucket name and file_key from the S3 event
        bucket_name = event['Records'][0]['s3']['bucket']['name']
        file_key = event['Records'][0]['s3']['object']['key']
        logging.info('parsing file %s in bucket %s', file_key, bucket_name)
        # get the object
        content_object = s3.get_object(Bucket=bucket_name, Key=file_key)
        logging.info('got file from S3')
        # get file content
        file_content = content_object['Body'].read().decode('utf-8')
        json_content = json.loads(file_content)
        # get required parameters
        resource_id = json_content['ConfigurationItem'].get('resourceId')
        resource_type = json_content['ConfigurationItem'].get('resourceType')
        resource_region = json_content['ConfigurationItem'].get('awsRegion')
        resource_zone = json_content['ConfigurationItem'].get('availabilityZone')
        resource_tags = json_content['ConfigurationItem'].get('tags')
        resource_relationships = json_content['ConfigurationItem'].get('relationships')

        return new_resource(resource_id, resource_type, resource_region, resource_zone, resource_tags, resource_relationships)

    except Exception as e:
        # Send some context about this error to Lambda Logs
        print(e)
        raise e
