// Native Windows Jenkins agent (JDK + Allure plugin assumed installed —
// see README "Jenkins setup" and docs/manual-tests.md for the one-time
// job configuration). Local Jenkins has no public URL for a webhook, so
// this polls SCM instead of listening for pushes.
pipeline {
    agent any

    triggers {
        pollSCM('H/5 * * * *')
    }

    options {
        timestamps()
    }

    stages {
        stage('Setup') {
            steps {
                // `py -3` = newest installed Python 3 (README floor: 3.11+),
                // so the pipeline is not coupled to one exact minor version.
                bat 'py -3 -m venv .venv'
                bat '.venv\\Scripts\\python.exe -m pip install -e ".[dev]"'
            }
        }

        stage('Regression') {
            steps {
                // Either suite failing fails this stage, and a failed stage
                // fails the build (bat returns non-zero -> pipeline goes RED).
                // This is deliberate: a regression suite that can't block a
                // merge isn't doing its job.
                bat '.venv\\Scripts\\python.exe -m pytest -q --alluredir=allure-results'
                bat '.venv\\Scripts\\python.exe -m behave -f allure_behave.formatter:AllureFormatter -o allure-results features'
            }
        }
    }

    post {
        always {
            allure includeProperties: false, results: [[path: 'allure-results']]
        }
    }
}
