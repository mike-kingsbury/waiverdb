import java.text.*

{% include "snippets/c3i-library.groovy" %}
pipeline {
  {% include "snippets/default-agent.groovy" %}
  options {
    timestamps()
    timeout(time: 30, unit: 'MINUTES')
  }
  stages {
    stage('Prepare') {
      steps {
        checkout([$class: 'GitSCM',
          branches: [[name: params.WAIVERDB_GIT_REF]],
          userRemoteConfigs: [[url: params.WAIVERDB_GIT_REPO, refspec: '+refs/heads/*:refs/remotes/origin/* +refs/pull/*/head:refs/remotes/origin/pull/*/head']],
        ])
      }
    }
    stage('Cleanup') {
      // Cleanup all test environments that were created 1 hour ago in case of failures of previous cleanups.
      steps {
        script {
          openshift.withCluster() {
            def df = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'")
            df.setTimeZone(TimeZone.getTimeZone('UTC'))
            // Get all OpenShift objects of previous test environments
            def oldObjs = openshift.selector('dc,deploy,configmap,secret,svc,route',
              ['template': 'waiverdb-test', 'app':'waiverdb'])
            def now = new Date()
            // Delete all objects that are older than 1 hour
            for (objName in oldObjs.names()) {
              def obj = openshift.selector(objName)
              def objData = obj.object()
              if (!objData.metadata.creationTimestamp)
                continue
              def creationTime = df.parse(objData.metadata.creationTimestamp)
              // 1 hour = 1000 * 60 * 60 ms
              if (now.getTime() - creationTime.getTime() < 1000 * 60 * 60)
                continue
              echo "Deleting ${objName}..."
              try {
                obj.delete()
                echo "Deleted ${objName}"
              } catch (e) {
                echo "Error deleting ${objName}: ${e.message}"
              }
            }
          }
        }
      }
    }
    stage('Run functional tests') {
      environment {
        // Jenkins BUILD_TAG could be too long (> 63 characters) for OpenShift to consume
        TEST_ID = "${params.TEST_ID ?: 'jenkins-' + currentBuild.id + '-' + UUID.randomUUID().toString().substring(0,7)}"
      }
      steps {
        echo "Container image ${params.IMAGE} will be tested."
        script {
          openshift.withCluster() {
            // Don't set ENVIRONMENT_LABEL in the environment block! Otherwise you will get 2 different UUIDs.
            env.ENVIRONMENT_LABEL = "test-${env.TEST_ID}"
            def template = readYaml file: 'openshift/waiverdb-test-template.yaml'
            def webPodReplicas = 1 // The current quota in UpShift is agressively limited
            echo "Creating testing environment with TEST_ID=${env.TEST_ID}..."
            def models = openshift.process(template,
              '-p', "TEST_ID=${env.TEST_ID}",
              '-p', "WAIVERDB_APP_IMAGE=${params.IMAGE}",
              '-p', "WAIVERDB_REPLICAS=${webPodReplicas}",
            )
            c3i.deployAndWait(script: this, objs: models, timeout: 15)
            def appPod = openshift.selector('pods', ['environment': env.ENVIRONMENT_LABEL, 'service': 'web']).object()
            env.IMAGE_DIGEST = appPod.status.containerStatuses[0].imageID.split('@')[1]
            // Run functional tests
            def route_hostname = openshift.selector('routes', ['environment': env.ENVIRONMENT_LABEL]).object().spec.host
            echo "Running tests against https://${route_hostname}/"
            withEnv(["WAIVERDB_TEST_URL=https://${route_hostname}/"]) {
              sh 'py.test-3 -v --junitxml=junit-functional-tests.xml functional-tests/'
            }
          }
        }
      }
      post {
        always {
          script {
            junit 'junit-functional-tests.xml'
            archiveArtifacts artifacts: 'junit-functional-tests.xml'
            openshift.withCluster() {
              /* Extract logs for debugging purposes */
              openshift.selector('deploy,pods', ['environment': env.ENVIRONMENT_LABEL]).logs()
            }
          }
        }
        cleanup {
          script {
            openshift.withCluster() {
              /* Tear down everything we just created */
              echo "Tearing down test resources..."
              try {
                openshift.selector('dc,deploy,rc,configmap,secret,svc,route',
                      ['environment': env.ENVIRONMENT_LABEL]).delete()
              } catch (e) {
                echo "Failed to tear down test resources: ${e.message}"
              }
            }
          }
        }
      }
    }
  }
  post {
    always {
      script {
        if (!env.IMAGE_DIGEST) {
          // Don't send a message if the job fails before getting the image digest.
          return;
        }
        // currentBuild.result == null || currentBuild.result == 'SUCCESS' indicates a successful build,
        // because it's possible that the pipeline engine hasn't set the value nor seen an error when reaching to this line.
        // See example code in https://jenkins.io/doc/book/pipeline/jenkinsfile/#deploy
        def sendResult = sendCIMessage \
          providerName: params.MESSAGING_PROVIDER, \
          overrides: [topic: 'VirtualTopic.eng.ci.container-image.test.complete'], \
          messageType: 'Custom', \
          messageProperties: '', \
          messageContent: """
          {
            "ci": {
              "name": "C3I Jenkins",
              "team": "DevOps",
              "url": "${env.JENKINS_URL}",
              "docs": "https://pagure.io/waiverdb/blob/master/f/openshift",
              "irc": "#pnt-devops-dev",
              "email": "pnt-factory2-devel@redhat.com",
              "environment": "stage"
            },
            "run": {
              "url": "${env.BUILD_URL}",
              "log": "${env.BUILD_URL}/console",
              "debug": "",
              "rebuild": "${env.BUILD_URL}/rebuild/parametrized"
            },
            "artifact": {
              "type": "container-image",
              "repository": "factory2/waiverdb",
              "digest": "${env.IMAGE_DIGEST}",
              "nvr": "${params.IMAGE}",
              "issuer": "c3i-jenkins",
              "scratch": ${params.IMAGE_IS_SCRATCH},
              "id": "waiverdb@${env.IMAGE_DIGEST}"
            },
            "system":
               [{
                  "os": "${params.JENKINS_AGENT_IMAGE}",
                  "provider": "openshift",
                  "architecture": "x86_64"
               }],
            "type": "integration",
            "category": "${params.ENVIRONMENT}",
            "status": "${currentBuild.result == null || currentBuild.result == 'SUCCESS' ? 'passed':'failed'}",
            "xunit": "${env.BUILD_URL}/artifacts/junit-functional-tests.xml",
            "generated_at": "${new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", TimeZone.getTimeZone('UTC'))}",
            "namespace": "c3i",
            "version": "0.1.0"
          }
          """
        if (sendResult.getMessageId()) {
          // echo sent message id and content
          echo 'Successfully sent the test result to ResultsDB.'
          echo "Message ID: ${sendResult.getMessageId()}"
          echo "Message content: ${sendResult.getMessageContent()}"
        } else {
          echo 'Failed to sent the test result to ResultsDB.'
        }
      }
    }
  }
}
