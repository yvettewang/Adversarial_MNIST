from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow as tf
import math
from mpl_toolkits.axes_grid1 import ImageGrid
import matplotlib.pyplot as plt

tf.logging.set_verbosity(tf.logging.INFO)


def find_all_2s(labels):
    index_of_2s = [i for i in range(len(labels)) if labels[i] == 2]
    return index_of_2s


def conv2d(x, W):
    return tf.nn.conv2d(x, W, strides=[1, 1, 1, 1], padding='SAME')


def max_pool_2x2(x):
    return tf.nn.max_pool(x, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1],
                          padding='SAME')


def plot_predictions(mnist_classifier, image_list, cnt, adversarial=False):
    # Using the pre-trained model to predict the images in the image_list.
    pred_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": image_list},
        num_epochs=1,
        shuffle=False)
    pred_results = list(
        mnist_classifier.predict(input_fn=pred_input_fn, checkpoint_path='./tmp/mnist_convnet_model/model.ckpt-20200'))

    pred_list = np.zeros(len(image_list)).astype(int)
    pct_list = np.zeros(len(image_list)).astype(int)

    # Setup image grid
    cols = 3
    rows = int(math.ceil(image_list.shape[0] / cols))
    fig = plt.figure(1, (12., 12.))
    fname = 'adv_image_' + str(cnt) + '.png'
    grid = ImageGrid(fig, 111,
                     nrows_ncols=(rows, cols),
                     axes_pad=0.5,
                     )

    # Get probs, images and populate grid
    for i in range(len(pred_results)):
        pred_list[i] = np.argmax(pred_results[i].get('probabilities'))
        pct_list[i] = pred_results[i].get('probabilities')[pred_list[i]] * 100
        image = image_list[i].reshape(28, 28)
        grid[i].imshow(image, cmap="gray")
        grid[i].set_title('Label: {0} \nCertainty: {1}%' \
                          .format(pred_list[i],
                                  pct_list[i]))
        # Only use when plotting original, partial deriv and adversarial images
        if (adversarial) & (i % 3 == 1):
            grid[i].set_title("Adversarial \nPartial Derivatives")
    plt.savefig('result_images/' + fname)
    plt.show()



def adversarial_image(mnist_classifier, true_images, fake_labels, lr, n_steps):
    """
    :param mnist_classifier: the pre-trained CNN model
    :param true_images: the image with the specific label
    :param fake_labels: an Integer indicating the fake label
    :param lr: learning rate
    :param n_steps: step to take to generate the adversarial images.
    """
    # reshape the input image as (1, 784)
    true_images = np.reshape(true_images, (1, 784))
    orig_images = true_images

    # generate one hot encoded fake label.
    fake_ = np.zeros((10, 1))
    fake_[fake_labels] = 1

    # calculate the loss between predicted label of the true image and the fake label.
    # input layer
    x = tf.placeholder(tf.float32, shape=[None, 784])
    x_image = tf.reshape(x, [-1, 28, 28, 1])

    # conv1 layer, loading weights and biases from the pretrained model.
    conv1_w = mnist_classifier.get_variable_value('conv2d/kernel')
    conv1_b = mnist_classifier.get_variable_value('conv2d/bias')
    conv1_o = tf.nn.relu(conv2d(x_image, conv1_w) + conv1_b)
    pool1_h = max_pool_2x2(conv1_o)

    # conv2 layer, loading weights and biases from the pretrained model.
    conv2_w = mnist_classifier.get_variable_value('conv2d_1/kernel')
    conv2_b = mnist_classifier.get_variable_value('conv2d_1/bias')
    conv2_o = tf.nn.relu(conv2d(pool1_h, conv2_w) + conv2_b)
    pool2_h = max_pool_2x2(conv2_o)

    # fully connected layer 1, loading weights and biases from the pretrained model.
    dense1_w = mnist_classifier.get_variable_value('dense/kernel')
    dense1_b = mnist_classifier.get_variable_value('dense/bias')
    pool2_flat = tf.reshape(pool2_h, [-1, 7 * 7 * 64])
    dense_o = tf.nn.relu(tf.matmul(pool2_flat, dense1_w) + dense1_b)

    # fully connected layer 2, loading weights and biases from the pretrained model.
    dense2_w = mnist_classifier.get_variable_value('dense_1/kernel')
    dense2_b = mnist_classifier.get_variable_value('dense_1/bias')
    dense2_o = tf.matmul(dense_o, dense2_w) + dense2_b

    # softmax the output of fully connected layer 2 to generate logits.
    logits = tf.nn.softmax(dense2_o)

    # calculate loss between fake label and predicted label.
    loss = tf.reduce_mean(
        tf.nn.softmax_cross_entropy_with_logits_v2(labels=fake_, logits=logits))

    # Take the derivatives of loss w.r.t. input image, and create adversarial image
    # This is inspired by:
    # https://codewords.recurse.com/issues/five/why-do-neural-networks-think-a-panda-is-a-vulture
    deriv = tf.gradients(loss, x)[0]
    image_adv = tf.stop_gradient(x - tf.sign(deriv) * lr / n_steps)
    image_adv = tf.clip_by_value(image_adv, 0, 1)

    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())

        # predicted label and reshape to (10, 1)
        y = sess.run(logits, feed_dict={x: true_images})
        y = np.reshape(y, (10, 1))

        for i in range(n_steps):
            # noise
            dydx = sess.run(deriv, feed_dict={x: true_images})  # 1 x 784

            # adversarial image
            x_adv = sess.run(image_adv, feed_dict={x: true_images})  # 1 x 784

            # Create darray of 3 images - orig, noise/delta, adversarial
            true_images = np.reshape(x_adv, (1, 784))
            img_adv_list = orig_images  # (1, 784)
            img_adv_list = np.append(img_adv_list, dydx, axis=0)
            img_adv_list = np.append(img_adv_list, true_images, axis=0)

            # Plot images
            plot_predictions(mnist_classifier, img_adv_list, i, adversarial=True)


def cnn_model_fn(features, labels, mode):
    """Model function for CNN."""
    # Input Layer
    # Reshape X to 4-D tensor: [batch_size, width, height, channels]
    # MNIST images are 28x28 pixels, and have one color channel
    input_layer = tf.reshape(features["x"], [-1, 28, 28, 1])

    # Convolutional Layer #1
    # Computes 32 features using a 5x5 filter with ReLU activation.
    # Padding is added to preserve width and height.
    # Input Tensor Shape: [batch_size, 28, 28, 1]
    # Output Tensor Shape: [batch_size, 28, 28, 32]
    conv1 = tf.layers.conv2d(
        inputs=input_layer,
        filters=32,
        kernel_size=[5, 5],
        padding="same",
        activation=tf.nn.relu)

    # Pooling Layer #1
    # First max pooling layer with a 2x2 filter and stride of 2
    # Input Tensor Shape: [batch_size, 28, 28, 32]
    # Output Tensor Shape: [batch_size, 14, 14, 32]
    pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)

    # Convolutional Layer #2
    # Computes 64 features using a 5x5 filter.
    # Padding is added to preserve width and height.
    # Input Tensor Shape: [batch_size, 14, 14, 32]
    # Output Tensor Shape: [batch_size, 14, 14, 64]
    conv2 = tf.layers.conv2d(
        inputs=pool1,
        filters=64,
        kernel_size=[5, 5],
        padding="same",
        activation=tf.nn.relu)

    # Pooling Layer #2
    # Second max pooling layer with a 2x2 filter and stride of 2
    # Input Tensor Shape: [batch_size, 14, 14, 64]
    # Output Tensor Shape: [batch_size, 7, 7, 64]
    pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)

    # Flatten tensor into a batch of vectors
    # Input Tensor Shape: [batch_size, 7, 7, 64]
    # Output Tensor Shape: [batch_size, 7 * 7 * 64]
    pool2_flat = tf.reshape(pool2, [-1, 7 * 7 * 64])

    # Dense Layer
    # Densely connected layer with 1024 neurons
    # Input Tensor Shape: [batch_size, 7 * 7 * 64]
    # Output Tensor Shape: [batch_size, 1024]
    dense = tf.layers.dense(inputs=pool2_flat, units=1024, activation=tf.nn.relu)

    # Add dropout operation; 0.6 probability that element will be kept
    dropout = tf.layers.dropout(
        inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)

    # Logits layer
    # Input Tensor Shape: [batch_size, 1024]
    # Output Tensor Shape: [batch_size, 10]
    logits = tf.layers.dense(inputs=dropout, units=10)

    predictions = {
        # Generate predictions (for PREDICT and EVAL mode)
        "classes": tf.argmax(input=logits, axis=1),
        # Add `softmax_tensor` to the graph. It is used for PREDICT and by the
        # `logging_hook`.
        "probabilities": tf.nn.softmax(logits, name="softmax_tensor")
    }
    if mode == tf.estimator.ModeKeys.PREDICT:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

    # Calculate Loss (for both TRAIN and EVAL modes)
    loss = tf.losses.sparse_softmax_cross_entropy(labels=labels, logits=logits)

    # Configure the Training Op (for TRAIN mode)
    if mode == tf.estimator.ModeKeys.TRAIN:
        optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.001)
        train_op = optimizer.minimize(
            loss=loss,
            global_step=tf.train.get_global_step())
        return tf.estimator.EstimatorSpec(mode=mode, loss=loss, train_op=train_op)

    # Add evaluation metrics (for EVAL mode)
    eval_metric_ops = {
        "accuracy": tf.metrics.accuracy(
            labels=labels, predictions=predictions["classes"])}
    return tf.estimator.EstimatorSpec(
        mode=mode, loss=loss, eval_metric_ops=eval_metric_ops)


def main(unused_argv):
    # Load training and eval data
    mnist = tf.contrib.learn.datasets.load_dataset("mnist")
    train_data = mnist.train.images  # Returns np.array
    train_labels = np.asarray(mnist.train.labels, dtype=np.int32)
    eval_data = mnist.test.images  # Returns np.array
    eval_labels = np.asarray(mnist.test.labels, dtype=np.int32)

    # Create the Estimator
    mnist_classifier = tf.estimator.Estimator(
        model_fn=cnn_model_fn, model_dir="./tmp/mnist_convnet_model")

    # Set up logging for predictions
    # Log the values in the "Softmax" tensor with label "probabilities"
    tensors_to_log = {"probabilities": "softmax_tensor"}
    logging_hook = tf.train.LoggingTensorHook(
        tensors=tensors_to_log, every_n_iter=50)

    # Train the model, uncomment the following line for training the model
    # train_input_fn = tf.estimator.inputs.numpy_input_fn(
    #     x={"x": train_data},
    #     y=train_labels,
    #     batch_size=50,
    #     num_epochs=None,
    #     shuffle=True)
    # mnist_classifier.train(
    #     input_fn=train_input_fn,
    #     steps=200,
    #     hooks=[logging_hook])

    # Evaluate the model and print results
    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data},
        y=eval_labels,
        num_epochs=1,
        shuffle=False)
    eval_results = mnist_classifier.evaluate(input_fn=eval_input_fn,
                                             checkpoint_path='./tmp/mnist_convnet_model/model.ckpt-20200')
    print('Evaluation result: ', eval_results)

    # randomly choose 9 images, uncomment the line to plot
    index_of_2s = find_all_2s(train_labels)
    x_batch = train_data[index_of_2s[10:19]]
    # plot_predictions(mnist_classifier, x_batch, -1)

    # Pick a random 2 image from first 1000 images
    # Create adversarial image and with target label 6
    rand_index = np.random.randint(0, len(index_of_2s))
    image = train_data[index_of_2s[rand_index]]
    label_adv = 6

    # Plot adversarial images
    # Over each step, model certainty changes from 2 to 6
    adversarial_image(mnist_classifier, image, label_adv, lr=0.25, n_steps=35)


if __name__ == "__main__":
    tf.app.run()
